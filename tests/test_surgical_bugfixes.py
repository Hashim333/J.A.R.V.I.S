"""
tests/test_surgical_bugfixes.py

Surgical regression tests for the confirmed bug-fix pass:

  Bug 1 — "open Chrome" must not enter profile selection; explicit profile
          requests ("open Chrome Hashi") still resolve to the right directory.
  Bug 2 — "open current tab" / "use current tab" / "in the current tab" must
          reach the browser handler, never the system-awareness answer.
  Bug 3 — explicit "search for Python in YouTube" executes directly without
          a replace/current/new-tab clarification.
  Bug 4 — url_loaded verification inspects the same CDP browser instance the
          executor drove; CDP-unavailable never fails a successful operation.
  Bug 5 — brain timeout handoff: near-deadline completion wins over TIMEOUT;
          hung operations still time out and signal cancellation.
  Bug 7 — shutdown stops promptly (watchdog wake, service stop bounds).

No microphone, network, model download, or real browser is used.
"""
from __future__ import annotations

import threading
import time
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from automation.apps import _ChromeProfile


def _chrome_profiles_4():
    return [
        _ChromeProfile(directory="Default", display_name="Muhammed"),
        _ChromeProfile(directory="Profile 1", display_name="Muhammed"),
        _ChromeProfile(directory="Profile 2", display_name="HASHI"),
        _ChromeProfile(directory="Profile 3", display_name="amithcs.in"),
    ]


# ===========================================================================
# Bug 1 — Chrome profile selection
# ===========================================================================

class TestOpenChromeNoProfilePrompt(unittest.TestCase):
    def test_plain_open_chrome_launches_default_without_asking(self) -> None:
        from automation import apps
        asked = []

        def fake_voice_input():
            asked.append(True)
            return "HASHI"

        with patch.object(apps, "_launch", return_value=True) as mock_launch:
            result = apps._open_chrome(voice_input=fake_voice_input, profile=None)
        self.assertTrue(result)
        self.assertEqual(asked, [], "plain 'open Chrome' must not prompt for a profile")
        mock_launch.assert_called_once_with("chrome")

    def test_explicit_profile_launches_matching_directory(self) -> None:
        from automation import apps
        with patch.object(apps, "_chrome_profiles", return_value=_chrome_profiles_4()):
            with patch.object(apps, "_launch", return_value=True) as mock_launch:
                self.assertTrue(apps._open_chrome(voice_input=None, profile="HASHI"))
        mock_launch.assert_called_once_with("chrome", ["--profile-directory=Profile 2"])

    def test_explicit_profile_by_directory(self) -> None:
        from automation import apps
        with patch.object(apps, "_chrome_profiles", return_value=_chrome_profiles_4()):
            with patch.object(apps, "_launch", return_value=True) as mock_launch:
                self.assertTrue(apps._open_chrome(voice_input=None, profile="Profile 3"))
        mock_launch.assert_called_once_with("chrome", ["--profile-directory=Profile 3"])

    def test_unknown_profile_does_not_silently_fall_back(self) -> None:
        from automation import apps
        from automation.apps import AppOperationError
        with patch.object(apps, "_chrome_profiles", return_value=_chrome_profiles_4()):
            with self.assertRaises(AppOperationError):
                apps._open_chrome(voice_input=None, profile="NoSuchProfile")


class TestInteractivePickerNoPrompt(unittest.TestCase):
    def test_no_profile_requested_returns_none_without_click_or_voice(self) -> None:
        import automation.interactive_launcher as il
        card = SimpleNamespace(text="HASHI")
        with patch.object(il.ui, "detect_window_by_title", return_value=object()):
            with patch.object(il.ui, "find_profile_cards", return_value=[card, SimpleNamespace(text="Muhammed")]):
                with patch.object(il.ui, "click_element") as mock_click:
                    result = il.handle_interactive_launch(
                        app_name="Google Chrome",
                        process_name="chrome.exe",
                        voice_input=lambda: (_ for _ in ()).throw(AssertionError("must not ask")),
                        profile=None,
                    )
        self.assertIsNone(result)
        mock_click.assert_not_called()

    def test_explicit_profile_clicks_matching_card(self) -> None:
        import automation.interactive_launcher as il
        cards = [SimpleNamespace(text="Muhammed"), SimpleNamespace(text="HASHI")]
        with patch.object(il.ui, "detect_window_by_title", return_value=object()):
            with patch.object(il.ui, "find_profile_cards", return_value=cards):
                with patch.object(il.ui, "click_element") as mock_click:
                    with patch.object(il, "_wait_for_chrome_ready", return_value=True):
                        result = il.handle_interactive_launch(
                            app_name="Google Chrome",
                            process_name="chrome.exe",
                            voice_input=None,
                            profile="HASHI",
                        )
        self.assertTrue(result["success"])
        mock_click.assert_called_once_with(cards[1])


def _apps_handler_with_app(canonical="Google Chrome", process="chrome.exe", exe="C:/chrome.exe"):
    from automation.handlers import AppsHandler
    handler = AppsHandler.__new__(AppsHandler)
    app_info = SimpleNamespace(
        canonical_name=canonical, process_name=process, executable=exe, launch_method="test",
    )
    registry = SimpleNamespace(lookup=lambda target: app_info)
    handler._app_registry = registry
    return handler


class TestOpenAppHandlerProfileRouting(unittest.TestCase):
    def test_running_chrome_without_profile_focuses_no_launch(self) -> None:
        from automation import apps as apps_mod
        from brain.execution_plan import Step
        handler = _apps_handler_with_app()
        step = Step(action="open_app", target="chrome",
                    parameters={"focus_if_running": True}, description="Open chrome.")
        with patch.object(apps_mod, "is_process_running", return_value=True):
            with patch.object(apps_mod, "focus_process",
                              return_value={"success": True, "message": "focused"}) as mock_focus:
                with patch.object(apps_mod, "launch_executable") as mock_launch:
                    result = handler._open_app("chrome", step, voice_input=lambda: "x")
        mock_focus.assert_called_once_with("chrome.exe")
        mock_launch.assert_not_called()
        self.assertTrue(result["success"])

    def test_running_chrome_with_explicit_profile_launches_it(self) -> None:
        from automation import apps as apps_mod
        from brain.execution_plan import Step
        handler = _apps_handler_with_app()
        step = Step(action="open_app", target="chrome",
                    parameters={"focus_if_running": True, "profile": "HASHI"},
                    description="Open chrome with profile 'HASHI'.")
        with patch.object(apps_mod, "_chrome_profiles", return_value=_chrome_profiles_4()):
            with patch.object(apps_mod, "is_process_running", return_value=True):
                with patch.object(apps_mod, "focus_process") as mock_focus:
                    with patch.object(apps_mod, "launch_executable",
                                       return_value={"success": True, "message": "launched"}) as mock_launch:
                        with patch.object(apps_mod, "verify_launch_by_process", return_value=True):
                            import automation.handlers as hmod
                            with patch.object(hmod.interactive, "handle_interactive_launch", return_value=None):
                                result = handler._open_app("chrome", step, voice_input=lambda: "x")
        mock_focus.assert_not_called()
        mock_launch.assert_called_once()
        _args, _kwargs = mock_launch.call_args
        self.assertIn("--profile-directory=Profile 2", _args[1])
        self.assertTrue(result["success"])

    def test_unknown_profile_is_reported_not_launched(self) -> None:
        from automation import apps as apps_mod
        from brain.execution_plan import Step
        handler = _apps_handler_with_app()
        step = Step(action="open_app", target="chrome",
                    parameters={"focus_if_running": True, "profile": "Nope"},
                    description="Open chrome.")
        with patch.object(apps_mod, "_chrome_profiles", return_value=_chrome_profiles_4()):
            with patch.object(apps_mod, "is_process_running", return_value=True):
                with patch.object(apps_mod, "launch_executable") as mock_launch:
                    result = handler._open_app("chrome", step, voice_input=None)
        mock_launch.assert_not_called()
        self.assertFalse(result["success"])
        self.assertIn("not found", result["message"])


# ===========================================================================
# Bug 2 — current-tab routing
# ===========================================================================

class TestCurrentTabNotSystemAwareness(unittest.TestCase):
    def _snapshot_with_chrome_windows(self):
        from system_awareness.answers import answer  # noqa (import to fail fast)
        from system_awareness.model import SystemAwarenessSnapshot, WindowInfo
        return SystemAwarenessSnapshot(
            timestamp=time.time(),
            windows=[
                WindowInfo(hwnd=1, pid=10, title="YouTube - Google Chrome",
                           is_active=True, is_visible=True),
                WindowInfo(hwnd=2, pid=11, title="Mail - Google Chrome",
                           is_active=False, is_visible=True),
            ],
        )

    def test_open_current_tab_not_answered(self) -> None:
        from system_awareness.answers import answer
        snap = self._snapshot_with_chrome_windows()
        for text in ("Open current tab.", "open current tab", "use current tab",
                     "in the current tab", "Use the current tab"):
            self.assertIsNone(answer(snap, text), f"{text!r} must fall through to the browser handler")

    def test_count_question_unaffected_by_current_tab_guard(self) -> None:
        # The guard must only divert direct current-tab commands: a genuine
        # count question must reach exactly the same code path as before.
        from system_awareness.answers import _CURRENT_TAB_ACTION, answer
        snap = self._snapshot_with_chrome_windows()
        question = "how many browser windows are open?"
        self.assertIsNone(_CURRENT_TAB_ACTION.search(question.casefold()))
        # answers.py has no count rule (returns None) — the guard must not
        # change that either way; the query stays on the normal path.
        self.assertIsNone(answer(snap, question))

    def test_parser_routes_current_tab_to_browser(self) -> None:
        from brain.parser import Parser
        parser = Parser()
        for text in ("Open current tab.", "use current tab", "in the current tab"):
            parsed = parser.parse(text)
            self.assertEqual(parsed.intent, "focus_app", text)
            self.assertEqual(parsed.entities.get("app_name"), "chrome", text)
        parsed = parser.parse("close current tab")
        self.assertEqual(parsed.intent, "close_current_tab")

    def test_parser_does_not_steal_count_question(self) -> None:
        from brain.parser import Parser
        parsed = Parser().parse("how many browser windows are open?")
        self.assertNotEqual(parsed.intent, "focus_app")

    def test_planner_builds_browser_steps(self) -> None:
        from brain.parser import Parser
        from brain.planner import Planner
        planner = Planner()
        plan = planner.create_plan(Parser().parse("Open current tab."))
        self.assertEqual(len(plan.steps), 1)
        self.assertEqual(plan.steps[0].action, "focus_app")
        plan = planner.create_plan(Parser().parse("close current tab"))
        self.assertEqual(plan.steps[0].action, "close_current_tab")


# ===========================================================================
# Bug 3 — explicit search provider executes directly
# ===========================================================================

class TestExplicitSearchProvider(unittest.TestCase):
    def test_parser_marks_explicit_provider(self) -> None:
        from brain.parser import Parser
        parser = Parser()
        parsed = parser.parse("search for Python in YouTube")
        self.assertEqual(parsed.intent, "search")
        self.assertEqual(parsed.entities.get("provider"), "youtube")
        self.assertEqual(parsed.entities.get("query"), "python")
        self.assertTrue(parsed.entities.get("provider_explicit"))

    def test_parser_default_search_is_not_explicit(self) -> None:
        from brain.parser import Parser
        parsed = Parser().parse("search for weather")
        self.assertEqual(parsed.intent, "search")
        self.assertEqual(parsed.entities.get("provider"), "google")
        self.assertFalse(parsed.entities.get("provider_explicit", False))

    def test_explicit_search_skips_clarification(self) -> None:
        from context_manager.context_manager import ContextManager
        cm = ContextManager()
        # Even with an existing search tab present, an explicit provider
        # must execute directly — the detector must not even be consulted.
        with patch.object(cm.browser_detector, "get_active_tab_across_browsers",
                           side_effect=AssertionError("must not consult tabs")):
            with patch.object(cm.browser_detector, "find_website_across_browsers",
                               side_effect=AssertionError("must not consult tabs")):
                result = cm.check_before_execution(
                    "search",
                    {"query": "Python", "provider": "youtube", "provider_explicit": True},
                    "search for Python in YouTube",
                )
        self.assertIsNone(result)

    def test_ambiguous_search_still_asks(self) -> None:
        from context_manager.browser_detector import BrowserInfo, BrowserTab, BrowserTabMatch
        from context_manager.context_manager import ContextManager
        cm = ContextManager()
        match = BrowserTabMatch(
            browser=BrowserInfo(name="chrome", display_name="Chrome",
                                process_name="chrome.exe", running=True, debug_port=9222),
            tab=BrowserTab(id=3, title="Google Search - cats",
                           url="https://www.google.com/search?q=cats",
                           active=False, window_id=1),
        )
        with patch.object(cm.browser_detector, "get_active_tab_across_browsers", return_value=None):
            with patch.object(cm.browser_detector, "find_website_across_browsers", return_value=[match]):
                result = cm.check_before_execution(
                    "search", {"query": "dogs", "provider": "google"}, "search dogs",
                )
        self.assertIsNotNone(result)
        self.assertTrue(result.needs_clarification)


# ===========================================================================
# Bug 4 — verification inspects the executor's browser instance
# ===========================================================================

class TestUrlLoadedVerificationContext(unittest.TestCase):
    def _check(self, target, ws_browsers, cdp_tabs):
        from intelligence.intelligent_planner import VerificationCheck
        from thinking.pipeline import PipelineEngine
        ws = SimpleNamespace(browsers=ws_browsers)
        check = VerificationCheck(kind="url_loaded", target=target)
        with patch("thinking.pipeline._cdp_browser_tabs", return_value=cdp_tabs):
            return PipelineEngine._check_world("url_loaded", check, ws)

    def test_cdp_tabs_authoritative(self) -> None:
        passed, message = self._check(
            "youtube.com", {},
            [("https://www.youtube.com/results?search_query=Python", "YouTube")],
        )
        self.assertTrue(passed, message)

    def test_cdp_unavailable_with_no_data_does_not_fail_success(self) -> None:
        passed, message = self._check("youtube.com", {}, None)
        self.assertTrue(passed, message)

    def test_cdp_empty_with_no_data_still_fails(self) -> None:
        passed, _message = self._check("youtube.com", {}, [])
        self.assertFalse(passed)

    def test_cdp_mismatch_still_fails(self) -> None:
        passed, _message = self._check(
            "youtube.com", {},
            [("https://www.google.com/search?q=cats", "Google")],
        )
        self.assertFalse(passed)

    def test_world_state_fallback_still_works(self) -> None:
        browser = SimpleNamespace(active_url="https://www.google.com/search?q=cats")
        passed, _message = self._check("google.com/search", {"chrome": browser}, [])
        self.assertTrue(passed)


# ===========================================================================
# Bug 5 — brain timeout handoff
# ===========================================================================

class TestBrainTimeoutHandoff(unittest.TestCase):
    def test_completion_during_grace_wins_over_timeout(self) -> None:
        from brain.brain import Brain
        from models.response import Response
        brain = Brain()

        def slow_but_bounded():
            time.sleep(0.4)
            return Response(success=True, message="done")

        started = time.monotonic()
        response = brain._run_with_timeout(slow_but_bounded, timeout=0.2)
        elapsed = time.monotonic() - started
        self.assertIsInstance(response, Response)
        self.assertTrue(response.success)
        self.assertEqual(response.message, "done")
        self.assertLess(elapsed, 5.0)

    def test_hung_operation_times_out_and_signals_cancel(self) -> None:
        from brain.brain import Brain
        brain = Brain()
        stop = threading.Event()
        cancel = threading.Event()

        def hang():
            stop.wait(30.0)
            from models.response import Response
            return Response(success=False, message="hang released")

        try:
            started = time.monotonic()
            response = brain._run_with_timeout(hang, timeout=0.3, cancel_event=cancel)
            elapsed = time.monotonic() - started
        finally:
            stop.set()
        self.assertFalse(response.success)
        self.assertEqual(response.task_result.value, "TIMEOUT")
        self.assertTrue(cancel.is_set(), "timed-out workers must observe cancellation")
        self.assertLess(elapsed, 5.0)


# ===========================================================================
# Bug 7 — shutdown promptness
# ===========================================================================

class TestShutdownPromptness(unittest.TestCase):
    def test_long_timeout_watchdog_stops_instantly(self) -> None:
        from monitoring.watchdog import Watchdog
        wd = Watchdog(name="test-backend", timeout=150.0)
        wd.start()
        try:
            started = time.monotonic()
            wd.stop()
            elapsed = time.monotonic() - started
        finally:
            wd.stop()
        self.assertLess(elapsed, 0.9, f"watchdog stop took {elapsed:.2f}s")

    def test_world_model_stop_prompt(self) -> None:
        from world_model.world_model import WorldModel
        model = WorldModel(collectors=[])
        model.start()
        started = time.monotonic()
        try:
            model.stop()
        finally:
            elapsed = time.monotonic() - started
        self.assertLess(elapsed, 2.5, f"world model stop took {elapsed:.2f}s")

    def test_awareness_stop_prompt(self) -> None:
        from system_awareness.system_awareness import SystemAwarenessService
        svc = SystemAwarenessService(collectors=[])
        svc.start()
        started = time.monotonic()
        try:
            svc.stop()
        finally:
            elapsed = time.monotonic() - started
        self.assertLess(elapsed, 2.5, f"awareness stop took {elapsed:.2f}s")


if __name__ == "__main__":
    unittest.main()
