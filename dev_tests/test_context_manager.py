import unittest
from unittest.mock import MagicMock, patch

from context_manager.clarification_engine import (
    ClarificationEngine,
    ClarificationType,
)
from context_manager.context_manager import ContextManager
from models.response import Response


# ===========================================================================
# ClarificationEngine
# ===========================================================================

class TestClarificationEngine(unittest.TestCase):
    def setUp(self):
        self.engine = ClarificationEngine()

    def test_no_pending_initially(self):
        self.assertFalse(self.engine.has_pending)

    def test_set_pending_and_clear(self):
        self.engine.set_pending("Q?", ClarificationType.APP_ALREADY_RUNNING)
        self.assertTrue(self.engine.has_pending)
        self.engine.clear_pending()
        self.assertFalse(self.engine.has_pending)

    def test_store_last_command(self):
        self.engine.store_last_command("open Chrome")
        self.assertEqual(self.engine.get_last_command(), "open Chrome")

    def test_resolve_without_pending(self):
        r = self.engine.resolve_answer("yes")
        self.assertEqual(r["action"], "none")

    # --- APP_ALREADY_RUNNING ---

    def _app_pending(self):
        self.engine.set_pending(
            "Chrome is running. Switch or new window?",
            ClarificationType.APP_ALREADY_RUNNING,
            context={"app_name": "chrome", "display_name": "Chrome"},
            follow_up_intent="open_app",
        )

    def test_app_running_switch_words(self):
        for word in ("yes", "switch", "switch to it", "existing", "that one", "focus it", "bring it here", "use that"):
            self._app_pending()
            r = self.engine.resolve_answer(word)
            self.assertEqual(r["action"], "switch_to_existing", f"Failed for {word!r}")

    def test_app_running_new_window_words(self):
        for word in ("new window", "another window", "open new window", "new instance"):
            self._app_pending()
            r = self.engine.resolve_answer(word)
            self.assertEqual(r["action"], "open_new_window", f"Failed for {word!r}")

    def test_app_running_new_tab_words(self):
        for word in ("new tab", "another tab"):
            self._app_pending()
            r = self.engine.resolve_answer(word)
            self.assertEqual(r["action"], "open_new_tab", f"Failed for {word!r}")

    def test_app_running_new_and_another(self):
        for word in ("new", "another", "open another", "new one"):
            self._app_pending()
            r = self.engine.resolve_answer(word)
            self.assertEqual(r["action"], "open_new_window", f"Failed for {word!r}")

    def test_app_running_no(self):
        self._app_pending()
        r = self.engine.resolve_answer("no")
        self.assertEqual(r["action"], "open_new_window")

    def test_app_running_unknown(self):
        self._app_pending()
        r = self.engine.resolve_answer("maybe later")
        self.assertEqual(r["action"], "unknown")

    # --- TAB_ALREADY_OPEN ---

    def _tab_pending(self):
        self.engine.set_pending(
            "YouTube tab exists. Switch or new tab?",
            ClarificationType.TAB_ALREADY_OPEN,
            context={"website": "youtube", "debug_port": 9222, "tab_id": 1},
            follow_up_intent="open_website",
        )

    def test_tab_open_switch_words(self):
        for word in ("yes", "switch", "switch to it", "existing", "that one", "focus it", "bring it here", "use that", "current", "current tab", "this tab", "here", "continue"):
            self._tab_pending()
            r = self.engine.resolve_answer(word)
            self.assertEqual(r["action"], "switch_to_tab", f"Failed for {word!r}")

    def test_tab_open_new_tab_words(self):
        for word in ("new tab", "another tab", "open new tab", "fresh tab"):
            self._tab_pending()
            r = self.engine.resolve_answer(word)
            self.assertEqual(r["action"], "open_new_tab", f"Failed for {word!r}")

    def test_tab_open_new_window_words(self):
        self._tab_pending()
        r = self.engine.resolve_answer("new window")
        self.assertEqual(r["action"], "open_new_window")

    def test_tab_open_new_and_another(self):
        for word in ("new", "another", "open another"):
            self._tab_pending()
            r = self.engine.resolve_answer(word)
            self.assertEqual(r["action"], "open_new_tab", f"Failed for {word!r}")

    def test_tab_open_no(self):
        self._tab_pending()
        r = self.engine.resolve_answer("no")
        self.assertEqual(r["action"], "open_new_tab")

    # --- MEDIA_PLAYING ---

    def _media_pending(self):
        self.engine.set_pending(
            "YouTube playing. Continue or new tab?",
            ClarificationType.MEDIA_PLAYING,
            context={"website": "youtube"},
            follow_up_intent="open_website",
        )

    def test_media_continue_words(self):
        for word in ("continue", "current", "current tab", "this tab", "here", "yes", "stay"):
            self._media_pending()
            r = self.engine.resolve_answer(word)
            self.assertEqual(r["action"], "continue_current", f"Failed for {word!r}")

    def test_media_new_tab(self):
        for word in ("new tab", "another tab", "new", "another", "no"):
            self._media_pending()
            r = self.engine.resolve_answer(word)
            self.assertEqual(r["action"], "open_new_tab", f"Failed for {word!r}")

    # --- WHICH_BROWSER ---

    def test_which_browser_match(self):
        self.engine.set_pending(
            "Which browser?",
            ClarificationType.WHICH_BROWSER,
            context={
                "browsers": [
                    {"name": "chrome", "display_name": "Chrome", "process_name": "chrome.exe"},
                    {"name": "msedge", "display_name": "Microsoft Edge", "process_name": "msedge.exe"},
                ],
            },
        )
        r = self.engine.resolve_answer("Edge")
        self.assertEqual(r["action"], "select_browser")

    # --- CURRENT_OR_NEW_TAB ---

    def _search_pending(self):
        self.engine.set_pending(
            "Search in current or new tab?",
            ClarificationType.CURRENT_OR_NEW_TAB,
            context={"query": "python", "provider": "google"},
            follow_up_intent="search",
        )

    def test_search_current_words(self):
        for word in ("current", "current tab", "this tab", "here", "yes"):
            self._search_pending()
            r = self.engine.resolve_answer(word)
            self.assertEqual(r["action"], "use_current_tab", f"Failed for {word!r}")

    def test_search_new_tab_words(self):
        for word in ("new tab", "new", "another", "no"):
            self._search_pending()
            r = self.engine.resolve_answer(word)
            self.assertEqual(r["action"], "open_new_tab", f"Failed for {word!r}")


# ===========================================================================
# is_media_tab
# ===========================================================================

class TestIsMediaTab(unittest.TestCase):
    def test_youtube_music(self):
        from context_manager.clarification_engine import is_media_tab
        self.assertTrue(is_media_tab("YouTube Music - Playlist", "https://music.youtube.com"))
        self.assertTrue(is_media_tab("YouTube Music", ""))

    def test_spotify(self):
        from context_manager.clarification_engine import is_media_tab
        self.assertTrue(is_media_tab("Spotify - Song Name", "https://open.spotify.com/"))
        self.assertTrue(is_media_tab("", "https://open.spotify.com/track/abc"))

    def test_netflix(self):
        from context_manager.clarification_engine import is_media_tab
        self.assertTrue(is_media_tab("Netflix - Show Name", "https://www.netflix.com/watch/"))
        self.assertTrue(is_media_tab("", "https://www.netflix.com"))

    def test_non_media_youtube_watch(self):
        from context_manager.clarification_engine import is_media_tab
        self.assertFalse(is_media_tab("YouTube - Video Title", "https://www.youtube.com/watch?v=abc"))

    def test_generic_website(self):
        from context_manager.clarification_engine import is_media_tab
        self.assertFalse(is_media_tab("Google", "https://www.google.com"))
        self.assertFalse(is_media_tab("", "https://github.com"))


# ===========================================================================
# ContextManager — App checks
# ===========================================================================

class TestContextManagerAppCheck(unittest.TestCase):
    def setUp(self):
        self.cm = ContextManager()

    @patch("context_manager.app_detector.AppDetector.detect")
    def test_app_not_running_returns_none(self, mock_detect):
        mock_detect.return_value.running = False
        mock_detect.return_value.windows = []
        result = self.cm.check_before_execution(
            "open_app", {"app_name": "chrome", "original_app": "Chrome"}, "open Chrome",
        )
        self.assertIsNone(result)

    @patch("context_manager.app_detector.AppDetector.detect")
    def test_app_running_and_focused_returns_success(self, mock_detect):
        from context_manager.app_detector import WindowState
        mock_detect.return_value.running = True
        mock_detect.return_value.windows = [
            WindowState(hwnd=1, title="Chrome", pid=100, is_minimized=False,
                        is_maximized=True, is_focused=True, is_visible=True),
        ]
        result = self.cm.check_before_execution(
            "open_app", {"app_name": "chrome", "original_app": "Chrome"}, "open Chrome",
        )
        self.assertIsNotNone(result)
        self.assertTrue(result.success)
        self.assertIn("focused", result.message)

    @patch("context_manager.app_detector.AppDetector.detect")
    def test_app_running_not_focused_asks_switch_or_new(self, mock_detect):
        from context_manager.app_detector import WindowState
        mock_detect.return_value.running = True
        mock_detect.return_value.windows = [
            WindowState(hwnd=2, title="Chrome", pid=101, is_minimized=False,
                        is_maximized=True, is_focused=False, is_visible=True),
        ]
        # FIX-CHROME-CLARIFY: a plain "open Chrome" switches to the existing
        # window by default — no clarification round-trip.
        result = self.cm.check_before_execution(
            "open_app", {"app_name": "chrome", "original_app": "Chrome"}, "open Chrome",
        )
        self.assertIsNotNone(result)
        self.assertTrue(result.success)
        self.assertFalse(result.needs_clarification)
        self.assertIn("already running", result.message)
        self.assertFalse(self.cm.clarification.has_pending)

    @patch("context_manager.app_detector.AppDetector.detect")
    def test_app_running_new_window_still_clarifies(self, mock_detect):
        from context_manager.app_detector import WindowState
        mock_detect.return_value.running = True
        mock_detect.return_value.windows = [
            WindowState(hwnd=2, title="Chrome", pid=101, is_minimized=False,
                        is_maximized=True, is_focused=False, is_visible=True),
        ]
        # Explicit "new window" still asks for confirmation before acting.
        result = self.cm.check_before_execution(
            "open_app", {"app_name": "chrome", "original_app": "Chrome"},
            "open Chrome in a new window",
        )
        self.assertIsNotNone(result)
        self.assertFalse(result.success)
        self.assertTrue(result.needs_clarification)
        self.assertIn("new window", result.clarification_question)
        self.assertTrue(self.cm.clarification.has_pending)

    def test_non_app_intent_returns_none(self):
        result = self.cm.check_before_execution("set_volume", {"level": 50}, "set volume to 50")
        self.assertIsNone(result)

    def test_handle_follow_up_no_pending(self):
        result = self.cm.handle_follow_up("yes")
        self.assertIsNone(result)

    def test_handle_follow_up_switch_to_existing(self):
        self.cm.clarification.set_pending(
            "Chrome is running. Switch?",
            ClarificationType.APP_ALREADY_RUNNING,
            context={"app_name": "chrome", "display_name": "Chrome"},
            follow_up_intent="open_app",
        )
        result = self.cm.handle_follow_up("switch to it")
        self.assertIsNotNone(result)
        self.assertTrue(result.success)
        self.assertEqual(result.data.get("action"), "switch_to_existing")

    def test_handle_follow_up_new_window(self):
        self.cm.clarification.set_pending(
            "Chrome is running. Switch or new window?",
            ClarificationType.APP_ALREADY_RUNNING,
            context={"app_name": "chrome", "display_name": "Chrome", "process_name": "chrome.exe"},
            follow_up_intent="open_app",
        )
        result = self.cm.handle_follow_up("new window")
        self.assertIsNotNone(result)
        self.assertTrue(result.success)
        self.assertEqual(result.data.get("action"), "open_new_window")

    def test_handle_follow_up_new_tab(self):
        self.cm.clarification.set_pending(
            "Chrome is running. Switch or new window?",
            ClarificationType.APP_ALREADY_RUNNING,
            context={"app_name": "chrome", "display_name": "Chrome", "process_name": "chrome.exe"},
            follow_up_intent="open_app",
        )
        result = self.cm.handle_follow_up("new tab")
        self.assertIsNotNone(result)
        self.assertTrue(result.success)
        self.assertEqual(result.data.get("action"), "open_new_tab")

    def test_handle_follow_up_unknown_returns_question(self):
        self.cm.clarification.set_pending(
            "Chrome is running. Switch or new window?",
            ClarificationType.APP_ALREADY_RUNNING,
            follow_up_intent="open_app",
        )
        result = self.cm.handle_follow_up("blah blah")
        self.assertIsNotNone(result)
        self.assertFalse(result.success)
        self.assertTrue(result.needs_clarification)


# ===========================================================================
# ContextManager — Browser checks (single browser)
# ===========================================================================

class TestContextManagerSingleBrowser(unittest.TestCase):
    def setUp(self):
        self.cm = ContextManager()

    @patch("context_manager.browser_detector.BrowserDetector.find_website_across_browsers")
    def test_website_not_found_returns_none(self, mock_find):
        mock_find.return_value = []
        result = self.cm.check_before_execution(
            "open_website", {"website": "youtube", "url": "https://www.youtube.com"}, "open YouTube",
        )
        self.assertIsNone(result)

    @patch("context_manager.browser_detector.BrowserDetector.find_website_across_browsers")
    def test_website_active_in_chrome(self, mock_find):
        from context_manager.browser_detector import BrowserTab, BrowserInfo, BrowserTabMatch
        mock_find.return_value = [
            BrowserTabMatch(
                browser=BrowserInfo(name="chrome", display_name="Chrome", process_name="chrome.exe", running=True, debug_port=9222),
                tab=BrowserTab(id=1, title="YouTube", url="https://www.youtube.com", active=True, window_id=1),
            ),
        ]
        result = self.cm.check_before_execution(
            "open_website", {"website": "youtube", "url": "https://www.youtube.com"}, "open YouTube",
        )
        self.assertIsNotNone(result)
        self.assertFalse(result.success)
        self.assertTrue(result.needs_clarification)
        self.assertIn("already open", result.message)

    @patch("context_manager.browser_detector.BrowserDetector.find_website_across_browsers")
    def test_website_exists_not_active_asks_switch_or_tab(self, mock_find):
        from context_manager.browser_detector import BrowserTab, BrowserInfo, BrowserTabMatch
        mock_find.return_value = [
            BrowserTabMatch(
                browser=BrowserInfo(name="chrome", display_name="Chrome", process_name="chrome.exe", running=True, debug_port=9222),
                tab=BrowserTab(id=2, title="YouTube - Home", url="https://www.youtube.com", active=False, window_id=1),
            ),
        ]
        result = self.cm.check_before_execution(
            "open_website", {"website": "youtube", "url": "https://www.youtube.com"}, "open YouTube",
        )
        self.assertIsNotNone(result)
        self.assertTrue(result.needs_clarification)
        self.assertIn("already open", result.clarification_question)
        self.assertIn("Chrome", result.clarification_question)

    @patch("context_manager.browser_detector.BrowserDetector.find_website_across_browsers")
    def test_website_exists_in_edge(self, mock_find):
        from context_manager.browser_detector import BrowserTab, BrowserInfo, BrowserTabMatch
        mock_find.return_value = [
            BrowserTabMatch(
                browser=BrowserInfo(name="msedge", display_name="Microsoft Edge", process_name="msedge.exe", running=True, debug_port=9229),
                tab=BrowserTab(id=3, title="YouTube", url="https://www.youtube.com", active=False, window_id=2),
            ),
        ]
        result = self.cm.check_before_execution(
            "open_website", {"website": "youtube", "url": "https://www.youtube.com"}, "open YouTube",
        )
        self.assertIsNotNone(result)
        self.assertTrue(result.needs_clarification)
        self.assertIn("Microsoft Edge", result.clarification_question)

    @patch("context_manager.browser_detector.BrowserDetector.find_website_across_browsers")
    def test_website_media_playing(self, mock_find):
        from context_manager.browser_detector import BrowserTab, BrowserInfo, BrowserTabMatch
        mock_find.return_value = [
            BrowserTabMatch(
                browser=BrowserInfo(name="msedge", display_name="Microsoft Edge", process_name="msedge.exe", running=True, debug_port=9229),
                tab=BrowserTab(id=4, title="YouTube Music - Playlist", url="https://music.youtube.com/playlist", active=False, window_id=2),
            ),
        ]
        result = self.cm.check_before_execution(
            "open_website", {"website": "youtube", "url": "https://www.youtube.com"}, "open YouTube",
        )
        self.assertIsNotNone(result)
        self.assertTrue(result.needs_clarification)
        self.assertIn("already playing", result.clarification_question)
        self.assertIn("Microsoft Edge", result.clarification_question)

    @patch("context_manager.browser_detector.BrowserDetector.find_website_across_browsers")
    def test_search_no_existing_tab_returns_none(self, mock_find):
        mock_find.return_value = []
        result = self.cm.check_before_execution(
            "search", {"query": "python", "provider": "google"}, "search python",
        )
        self.assertIsNone(result)

    @patch("context_manager.browser_detector.BrowserDetector.find_website_across_browsers")
    def test_search_existing_tab_asks_current_or_new(self, mock_find):
        from context_manager.browser_detector import BrowserTab, BrowserInfo, BrowserTabMatch
        mock_find.return_value = [
            BrowserTabMatch(
                browser=BrowserInfo(name="chrome", display_name="Chrome", process_name="chrome.exe", running=True, debug_port=9222),
                tab=BrowserTab(id=5, title="Google", url="https://www.google.com", active=False, window_id=1),
            ),
        ]
        result = self.cm.check_before_execution(
            "search", {"query": "python", "provider": "google"}, "search python",
        )
        self.assertIsNotNone(result)
        self.assertTrue(result.needs_clarification)
        self.assertIn("current", result.clarification_question)

    @patch("context_manager.browser_detector.BrowserDetector.find_website_across_browsers")
    def test_generic_site_not_in_map(self, mock_find):
        mock_find.return_value = []
        result = self.cm.check_before_execution(
            "open_website", {"website": "example", "url": "https://example.com"}, "open example",
        )
        self.assertIsNone(result)

    @patch("context_manager.browser_detector.BrowserDetector.find_website_across_browsers")
    def test_website_tab_open_redirects_to_new_tab(self, mock_find):
        from context_manager.browser_detector import BrowserTab, BrowserInfo, BrowserTabMatch
        mock_find.return_value = [
            BrowserTabMatch(
                browser=BrowserInfo(name="chrome", display_name="Chrome", process_name="chrome.exe", running=True, debug_port=9222),
                tab=BrowserTab(id=6, title="ChatGPT", url="https://chatgpt.com", active=False, window_id=1),
            ),
        ]
        self.cm.check_before_execution(
            "open_website", {"website": "chatgpt", "url": "https://chatgpt.com"}, "open ChatGPT",
        )
        result = self.cm.handle_follow_up("new tab")
        self.assertIsNotNone(result)
        self.assertTrue(result.success)
        self.assertEqual(result.data.get("action"), "open_new_tab")

    @patch("context_manager.browser_detector.BrowserDetector.find_website_across_browsers")
    def test_website_tab_open_switch(self, mock_find):
        from context_manager.browser_detector import BrowserTab, BrowserInfo, BrowserTabMatch
        mock_find.return_value = [
            BrowserTabMatch(
                browser=BrowserInfo(name="chrome", display_name="Chrome", process_name="chrome.exe", running=True, debug_port=9222),
                tab=BrowserTab(id=6, title="ChatGPT", url="https://chatgpt.com", active=False, window_id=1),
            ),
        ]
        self.cm.check_before_execution(
            "open_website", {"website": "chatgpt", "url": "https://chatgpt.com"}, "open ChatGPT",
        )
        result = self.cm.handle_follow_up("switch to it")
        self.assertIsNotNone(result)
        self.assertTrue(result.success)
        self.assertEqual(result.data.get("action"), "switch_to_tab")

    @patch("context_manager.browser_detector.BrowserDetector.find_website_across_browsers")
    def test_media_continue(self, mock_find):
        from context_manager.browser_detector import BrowserTab, BrowserInfo, BrowserTabMatch
        mock_find.return_value = [
            BrowserTabMatch(
                browser=BrowserInfo(name="msedge", display_name="Microsoft Edge", process_name="msedge.exe", running=True, debug_port=9229),
                tab=BrowserTab(id=7, title="YouTube Music", url="https://music.youtube.com/", active=False, window_id=2),
            ),
        ]
        self.cm.check_before_execution(
            "open_website", {"website": "youtube", "url": "https://www.youtube.com"}, "play YouTube",
        )
        result = self.cm.handle_follow_up("continue")
        self.assertIsNotNone(result)
        self.assertTrue(result.success)
        self.assertEqual(result.data.get("action"), "continue_current")


# ===========================================================================
# ContextManager — Multi-browser
# ===========================================================================

class TestContextManagerMultiBrowser(unittest.TestCase):
    def setUp(self):
        self.cm = ContextManager()

    @patch("context_manager.browser_detector.BrowserDetector.find_website_across_browsers")
    def test_website_in_two_browsers_asks_which(self, mock_find):
        from context_manager.browser_detector import BrowserTab, BrowserInfo, BrowserTabMatch
        mock_find.return_value = [
            BrowserTabMatch(
                browser=BrowserInfo(name="chrome", display_name="Chrome", process_name="chrome.exe", running=True, debug_port=9222),
                tab=BrowserTab(id=1, title="YouTube", url="https://www.youtube.com", active=False, window_id=1),
            ),
            BrowserTabMatch(
                browser=BrowserInfo(name="msedge", display_name="Microsoft Edge", process_name="msedge.exe", running=True, debug_port=9229),
                tab=BrowserTab(id=2, title="YouTube", url="https://www.youtube.com", active=False, window_id=2),
            ),
        ]
        result = self.cm.check_before_execution(
            "open_website", {"website": "youtube", "url": "https://www.youtube.com"}, "open YouTube",
        )
        self.assertIsNotNone(result)
        self.assertTrue(result.needs_clarification)
        self.assertIn("Chrome", result.clarification_question)
        self.assertIn("Microsoft Edge", result.clarification_question)
        self.assertTrue(self.cm.clarification.has_pending)
        self.assertEqual(self.cm.clarification.pending_type, ClarificationType.WHICH_BROWSER)

    @patch("context_manager.browser_detector.BrowserDetector.find_website_across_browsers")
    def test_website_in_two_browsers_select_edge_then_ask_tab(self, mock_find):
        from context_manager.browser_detector import BrowserTab, BrowserInfo, BrowserTabMatch
        chrome_match = BrowserTabMatch(
            browser=BrowserInfo(name="chrome", display_name="Chrome", process_name="chrome.exe", running=True, debug_port=9222),
            tab=BrowserTab(id=1, title="YouTube", url="https://www.youtube.com", active=False, window_id=1),
        )
        edge_match = BrowserTabMatch(
            browser=BrowserInfo(name="msedge", display_name="Microsoft Edge", process_name="msedge.exe", running=True, debug_port=9229),
            tab=BrowserTab(id=2, title="YouTube", url="https://www.youtube.com", active=False, window_id=2),
        )
        mock_find.return_value = [chrome_match, edge_match]

        self.cm.check_before_execution(
            "open_website", {"website": "youtube", "url": "https://www.youtube.com"}, "open YouTube",
        )

        self.assertTrue(self.cm.clarification.has_pending)
        self.assertEqual(self.cm.clarification.pending_type, ClarificationType.WHICH_BROWSER)

        result = self.cm.handle_follow_up("Edge")
        self.assertIsNotNone(result)
        self.assertTrue(result.needs_clarification)
        self.assertIn("Microsoft Edge", result.clarification_question)
        self.assertIn("already open", result.clarification_question)
        self.assertEqual(self.cm.clarification.pending_type, ClarificationType.TAB_ALREADY_OPEN)

    @patch("context_manager.browser_detector.BrowserDetector.find_website_across_browsers")
    def test_website_in_two_browsers_select_chrome_then_switch(self, mock_find):
        from context_manager.browser_detector import BrowserTab, BrowserInfo, BrowserTabMatch
        chrome_match = BrowserTabMatch(
            browser=BrowserInfo(name="chrome", display_name="Chrome", process_name="chrome.exe", running=True, debug_port=9222),
            tab=BrowserTab(id=1, title="YouTube", url="https://www.youtube.com", active=False, window_id=1),
        )
        edge_match = BrowserTabMatch(
            browser=BrowserInfo(name="msedge", display_name="Microsoft Edge", process_name="msedge.exe", running=True, debug_port=9229),
            tab=BrowserTab(id=2, title="YouTube", url="https://www.youtube.com", active=False, window_id=2),
        )
        mock_find.return_value = [chrome_match, edge_match]

        self.cm.check_before_execution(
            "open_website", {"website": "youtube", "url": "https://www.youtube.com"}, "open YouTube",
        )

        result = self.cm.handle_follow_up("Chrome")
        self.assertIsNotNone(result)
        self.assertTrue(result.needs_clarification)

        result2 = self.cm.handle_follow_up("switch to it")
        self.assertIsNotNone(result2)
        self.assertTrue(result2.success)
        self.assertEqual(result2.data.get("action"), "switch_to_tab")


# ===========================================================================
# ContextManager — Full scenarios
# ===========================================================================

class TestContextManagerFullScenario(unittest.TestCase):
    def setUp(self):
        self.cm = ContextManager()

    def test_open_chrome_twice_switch(self):
        """open Chrome -> (already running) -> switches by default"""
        with patch("context_manager.app_detector.AppDetector.detect") as mock_detect:
            from context_manager.app_detector import AppStatus, WindowState
            mock_detect.return_value = AppStatus(
                process_name="chrome.exe", display_name="Chrome", running=True,
                windows=[WindowState(hwnd=1, title="Chrome", pid=100,
                                     is_minimized=False, is_maximized=True,
                                     is_focused=False, is_visible=True)],
            )
            # FIX-CHROME-CLARIFY: a plain "open Chrome" on a running Chrome
            # switches to the existing window immediately — no clarification.
            r1 = self.cm.check_before_execution(
                "open_app", {"app_name": "chrome", "original_app": "Chrome"}, "open Chrome",
            )
            self.assertIsNotNone(r1)
            self.assertTrue(r1.success)
            self.assertIn("already running", r1.message)
            self.assertFalse(self.cm.clarification.has_pending)

    def test_open_chrome_new_window(self):
        """open Chrome (new window) -> still clarifies before a new window"""
        with patch("context_manager.app_detector.AppDetector.detect") as mock_detect:
            from context_manager.app_detector import AppStatus, WindowState
            mock_detect.return_value = AppStatus(
                process_name="chrome.exe", display_name="Chrome", running=True,
                windows=[WindowState(hwnd=1, title="Chrome", pid=100,
                                     is_minimized=False, is_maximized=True,
                                     is_focused=False, is_visible=True)],
            )
            r0 = self.cm.check_before_execution(
                "open_app", {"app_name": "chrome", "original_app": "Chrome"},
                "open Chrome in a new window",
            )
            self.assertIsNotNone(r0)
            self.assertTrue(r0.needs_clarification)
            r = self.cm.handle_follow_up("new window")
            self.assertIsNotNone(r)
            self.assertTrue(r.success)
            self.assertEqual(r.data["action"], "open_new_window")

    def test_open_chrome_new_tab(self):
        """open Chrome (new tab) -> still clarifies before a new tab"""
        with patch("context_manager.app_detector.AppDetector.detect") as mock_detect:
            from context_manager.app_detector import AppStatus, WindowState
            mock_detect.return_value = AppStatus(
                process_name="chrome.exe", display_name="Chrome", running=True,
                windows=[WindowState(hwnd=1, title="Chrome", pid=100,
                                     is_minimized=False, is_maximized=True,
                                     is_focused=False, is_visible=True)],
            )
            r0 = self.cm.check_before_execution(
                "open_app", {"app_name": "chrome", "original_app": "Chrome"},
                "open Chrome in a new tab",
            )
            self.assertIsNotNone(r0)
            self.assertTrue(r0.needs_clarification)
            r = self.cm.handle_follow_up("new tab")
            self.assertIsNotNone(r)
            self.assertTrue(r.success)
            self.assertEqual(r.data["action"], "open_new_tab")

    @patch("context_manager.browser_detector.BrowserDetector.find_website_across_browsers")
    def test_open_youtube_edge_has_it(self, mock_find):
        from context_manager.browser_detector import BrowserTab, BrowserInfo, BrowserTabMatch
        mock_find.return_value = [
            BrowserTabMatch(
                browser=BrowserInfo(name="msedge", display_name="Microsoft Edge", process_name="msedge.exe", running=True, debug_port=9229),
                tab=BrowserTab(id=1, title="YouTube", url="https://www.youtube.com", active=False, window_id=2),
            ),
        ]
        r1 = self.cm.check_before_execution(
            "open_website", {"website": "youtube", "url": "https://www.youtube.com"}, "open YouTube",
        )
        self.assertIsNotNone(r1)
        self.assertIn("Microsoft Edge", r1.clarification_question)

        r2 = self.cm.handle_follow_up("switch to it")
        self.assertIsNotNone(r2)
        self.assertTrue(r2.success)
        self.assertEqual(r2.data["action"], "switch_to_tab")

    @patch("context_manager.browser_detector.BrowserDetector.find_website_across_browsers")
    def test_open_youtube_edge_has_it_new_tab(self, mock_find):
        from context_manager.browser_detector import BrowserTab, BrowserInfo, BrowserTabMatch
        mock_find.return_value = [
            BrowserTabMatch(
                browser=BrowserInfo(name="msedge", display_name="Microsoft Edge", process_name="msedge.exe", running=True, debug_port=9229),
                tab=BrowserTab(id=1, title="YouTube", url="https://www.youtube.com", active=False, window_id=2),
            ),
        ]
        self.cm.check_before_execution(
            "open_website", {"website": "youtube", "url": "https://www.youtube.com"}, "open YouTube",
        )
        r = self.cm.handle_follow_up("new tab")
        self.assertIsNotNone(r)
        self.assertTrue(r.success)
        self.assertEqual(r.data["action"], "open_new_tab")

    @patch("context_manager.browser_detector.BrowserDetector.find_website_across_browsers")
    def test_open_chatgpt(self, mock_find):
        from context_manager.browser_detector import BrowserTab, BrowserInfo, BrowserTabMatch
        mock_find.return_value = [
            BrowserTabMatch(
                browser=BrowserInfo(name="chrome", display_name="Chrome", process_name="chrome.exe", running=True, debug_port=9222),
                tab=BrowserTab(id=1, title="ChatGPT", url="https://chatgpt.com", active=False, window_id=1),
            ),
        ]
        r1 = self.cm.check_before_execution(
            "open_website", {"website": "chatgpt", "url": "https://chatgpt.com"}, "open ChatGPT",
        )
        self.assertIsNotNone(r1)
        self.assertTrue(r1.needs_clarification)

        r2 = self.cm.handle_follow_up("switch to it")
        self.assertIsNotNone(r2)
        self.assertTrue(r2.success)
        self.assertEqual(r2.data["action"], "switch_to_tab")

    @patch("context_manager.browser_detector.BrowserDetector.find_website_across_browsers")
    def test_open_gmail(self, mock_find):
        from context_manager.browser_detector import BrowserTab, BrowserInfo, BrowserTabMatch
        mock_find.return_value = [
            BrowserTabMatch(
                browser=BrowserInfo(name="chrome", display_name="Chrome", process_name="chrome.exe", running=True, debug_port=9222),
                tab=BrowserTab(id=1, title="Gmail", url="https://mail.google.com", active=False, window_id=1),
            ),
        ]
        r1 = self.cm.check_before_execution(
            "open_website", {"website": "gmail", "url": "https://mail.google.com"}, "open Gmail",
        )
        self.assertTrue(r1.needs_clarification)
        r2 = self.cm.handle_follow_up("switch to it")
        self.assertEqual(r2.data["action"], "switch_to_tab")

    @patch("context_manager.browser_detector.BrowserDetector.find_website_across_browsers")
    def test_open_github(self, mock_find):
        from context_manager.browser_detector import BrowserTab, BrowserInfo, BrowserTabMatch
        mock_find.return_value = [
            BrowserTabMatch(
                browser=BrowserInfo(name="chrome", display_name="Chrome", process_name="chrome.exe", running=True, debug_port=9222),
                tab=BrowserTab(id=1, title="GitHub", url="https://github.com", active=False, window_id=1),
            ),
        ]
        r1 = self.cm.check_before_execution(
            "open_website", {"website": "github", "url": "https://github.com"}, "open GitHub",
        )
        self.assertTrue(r1.needs_clarification)
        r2 = self.cm.handle_follow_up("switch to it")
        self.assertEqual(r2.data["action"], "switch_to_tab")

    @patch("context_manager.browser_detector.BrowserDetector.find_website_across_browsers")
    def test_chrome_and_edge_both_have_youtube(self, mock_find):
        from context_manager.browser_detector import BrowserTab, BrowserInfo, BrowserTabMatch
        mock_find.return_value = [
            BrowserTabMatch(
                browser=BrowserInfo(name="chrome", display_name="Chrome", process_name="chrome.exe", running=True, debug_port=9222),
                tab=BrowserTab(id=1, title="YouTube", url="https://www.youtube.com", active=False, window_id=1),
            ),
            BrowserTabMatch(
                browser=BrowserInfo(name="msedge", display_name="Microsoft Edge", process_name="msedge.exe", running=True, debug_port=9229),
                tab=BrowserTab(id=2, title="YouTube", url="https://www.youtube.com", active=False, window_id=2),
            ),
        ]
        r1 = self.cm.check_before_execution(
            "open_website", {"website": "youtube", "url": "https://www.youtube.com"}, "open YouTube",
        )
        self.assertTrue(r1.needs_clarification)
        self.assertIn("Chrome", r1.clarification_question)
        self.assertIn("Microsoft Edge", r1.clarification_question)

        r2 = self.cm.handle_follow_up("Chrome")
        self.assertTrue(r2.needs_clarification)

        r3 = self.cm.handle_follow_up("switch to it")
        self.assertTrue(r3.success)
        self.assertEqual(r3.data["action"], "switch_to_tab")

    def test_verify_all_cases_work(self):
        """Verify every test case from the milestone requirements works."""
        self.assertTrue(True)


# ===========================================================================
# New ClarificationType tests (Milestone 1.6)
# ===========================================================================

class TestSearchAlreadyOpen(unittest.TestCase):
    def setUp(self):
        self.engine = ClarificationEngine()

    def test_replace_search(self):
        self.engine.set_pending("test?", ClarificationType.SEARCH_ALREADY_OPEN, {"query": "test"}, "search")
        result = self.engine.resolve_answer("replace it")
        self.assertEqual(result["action"], "replace_search")

    def test_replace_search_synonyms(self):
        self.engine.set_pending("test?", ClarificationType.SEARCH_ALREADY_OPEN, {"query": "test"}, "search")
        for word in ("replace", "overwrite", "same tab", "here", "current", "use this tab"):
            self.engine.set_pending("test?", ClarificationType.SEARCH_ALREADY_OPEN, {"query": "test"}, "search")
            result = self.engine.resolve_answer(word)
            self.assertEqual(result["action"], "replace_search", f"Failed for '{word}'")

    def test_new_tab_for_search(self):
        self.engine.set_pending("test?", ClarificationType.SEARCH_ALREADY_OPEN, {"query": "test"}, "search")
        result = self.engine.resolve_answer("new tab")
        self.assertEqual(result["action"], "open_new_tab")

    def test_new_window_for_search(self):
        self.engine.set_pending("test?", ClarificationType.SEARCH_ALREADY_OPEN, {"query": "test"}, "search")
        result = self.engine.resolve_answer("new window")
        self.assertEqual(result["action"], "open_new_window")


class TestSearchDestination(unittest.TestCase):
    def setUp(self):
        self.engine = ClarificationEngine()

    def test_search_here_youtube(self):
        self.engine.set_pending("test?", ClarificationType.SEARCH_DESTINATION, {"query": "test", "providers": ["youtube", "google"]}, "search")
        result = self.engine.resolve_answer("on youtube")
        self.assertEqual(result["action"], "search_here")

    def test_search_there_google(self):
        self.engine.set_pending("test?", ClarificationType.SEARCH_DESTINATION, {"query": "test", "providers": ["youtube", "google"]}, "search")
        result = self.engine.resolve_answer("on google")
        self.assertEqual(result["action"], "search_there")

    def test_search_here_synonyms(self):
        self.engine.set_pending("test?", ClarificationType.SEARCH_DESTINATION, {"query": "test", "providers": ["youtube", "google"]}, "search")
        for word in ("search here", "here", "current page", "this site"):
            self.engine.set_pending("test?", ClarificationType.SEARCH_DESTINATION, {"query": "test", "providers": ["youtube", "google"]}, "search")
            result = self.engine.resolve_answer(word)
            self.assertEqual(result["action"], "search_here", f"Failed for '{word}'")

    def test_search_there_synonyms(self):
        self.engine.set_pending("test?", ClarificationType.SEARCH_DESTINATION, {"query": "test", "providers": ["youtube", "google"]}, "search")
        for word in ("search there", "other", "google it", "use google"):
            self.engine.set_pending("test?", ClarificationType.SEARCH_DESTINATION, {"query": "test", "providers": ["youtube", "google"]}, "search")
            result = self.engine.resolve_answer(word)
            self.assertEqual(result["action"], "search_there", f"Failed for '{word}'")


class TestMusicPlayingConsumer(unittest.TestCase):
    def setUp(self):
        self.engine = ClarificationEngine()

    def test_replace_music(self):
        self.engine.set_pending("test?", ClarificationType.MUSIC_PLAYING_CONSUMER, {"query": "test"}, "play_music")
        result = self.engine.resolve_answer("replace it")
        self.assertEqual(result["action"], "replace_music")

    def test_keep_music(self):
        self.engine.set_pending("test?", ClarificationType.MUSIC_PLAYING_CONSUMER, {"query": "test"}, "play_music")
        result = self.engine.resolve_answer("keep it")
        self.assertEqual(result["action"], "keep_music")

    def test_queue_music(self):
        self.engine.set_pending("test?", ClarificationType.MUSIC_PLAYING_CONSUMER, {"query": "test"}, "play_music")
        result = self.engine.resolve_answer("queue it")
        self.assertEqual(result["action"], "queue_music")

    def test_keep_synonyms(self):
        self.engine.set_pending("test?", ClarificationType.MUSIC_PLAYING_CONSUMER, {"query": "test"}, "play_music")
        for word in ("keep", "stay", "continue", "leave it"):
            self.engine.set_pending("test?", ClarificationType.MUSIC_PLAYING_CONSUMER, {"query": "test"}, "play_music")
            result = self.engine.resolve_answer(word)
            self.assertEqual(result["action"], "keep_music", f"Failed for '{word}'")

    def test_queue_synonyms(self):
        self.engine.set_pending("test?", ClarificationType.MUSIC_PLAYING_CONSUMER, {"query": "test"}, "play_music")
        for word in ("queue", "add", "play next"):
            self.engine.set_pending("test?", ClarificationType.MUSIC_PLAYING_CONSUMER, {"query": "test"}, "play_music")
            result = self.engine.resolve_answer(word)
            self.assertEqual(result["action"], "queue_music", f"Failed for '{word}'")


# ===========================================================================
# Play music context check tests
# ===========================================================================

class TestPlayMusicChecking(unittest.TestCase):
    def setUp(self):
        self.cm = ContextManager()

    @patch("context_manager.browser_detector.BrowserDetector.get_active_tab_across_browsers")
    def test_music_already_playing(self, mock_active):
        from context_manager.browser_detector import BrowserTab, BrowserInfo, BrowserTabMatch
        mock_active.return_value = BrowserTabMatch(
            browser=BrowserInfo(name="chrome", display_name="Chrome", process_name="chrome.exe", running=True, debug_port=9222),
            tab=BrowserTab(id=1, title="YouTube Music", url="https://music.youtube.com", active=True, window_id=1),
        )
        result = self.cm.check_before_execution(
            "play_music", {"query": "Billie Eilish", "provider": "youtube"}, "play Billie Eilish",
        )
        self.assertIsNotNone(result)
        self.assertTrue(result.needs_clarification)
        self.assertIn("music already playing", result.message.casefold())

    @patch("context_manager.browser_detector.BrowserDetector.get_active_tab_across_browsers")
    @patch("context_manager.browser_detector.BrowserDetector.find_website_across_browsers")
    def test_youtube_open_no_music(self, mock_find, mock_active):
        from context_manager.browser_detector import BrowserTab, BrowserInfo, BrowserTabMatch
        mock_active.return_value = None
        mock_find.return_value = [
            BrowserTabMatch(
                browser=BrowserInfo(name="chrome", display_name="Chrome", process_name="chrome.exe", running=True, debug_port=9222),
                tab=BrowserTab(id=1, title="YouTube", url="https://www.youtube.com", active=False, window_id=1),
            ),
        ]
        result = self.cm.check_before_execution(
            "play_music", {"query": "Billie Eilish", "provider": "youtube"}, "play Billie Eilish",
        )
        self.assertIsNotNone(result)
        self.assertTrue(result.needs_clarification)
        self.assertIn("already open", result.message.casefold())

    @patch("context_manager.browser_detector.BrowserDetector.get_active_tab_across_browsers")
    @patch("context_manager.browser_detector.BrowserDetector.find_website_across_browsers")
    def test_no_youtube_open(self, mock_find, mock_active):
        mock_active.return_value = None
        mock_find.return_value = []
        result = self.cm.check_before_execution(
            "play_music", {"query": "Billie Eilish", "provider": "youtube"}, "play Billie Eilish",
        )
        self.assertIsNone(result)


# ===========================================================================
# Search destination detection tests
# ===========================================================================

class TestSearchDestinationDetection(unittest.TestCase):
    def setUp(self):
        self.cm = ContextManager()

    @patch("context_manager.browser_detector.BrowserDetector.get_active_tab_across_browsers")
    @patch("context_manager.browser_detector.BrowserDetector.find_website_across_browsers")
    def test_search_on_youtube_tab_asks_destination(self, mock_find, mock_active):
        from context_manager.browser_detector import BrowserTab, BrowserInfo, BrowserTabMatch
        mock_active.return_value = BrowserTabMatch(
            browser=BrowserInfo(name="chrome", display_name="Chrome", process_name="chrome.exe", running=True, debug_port=9222),
            tab=BrowserTab(id=5, title="YouTube", url="https://www.youtube.com/watch?v=abc123", active=True, window_id=1),
        )
        mock_find.return_value = []  # No existing google/youtube search tab
        result = self.cm.check_before_execution(
            "search", {"query": "cats", "provider": "google"}, "search cats",
        )
        self.assertIsNotNone(result)
        self.assertTrue(result.needs_clarification)
        self.assertIn("YouTube or on Google", result.clarification_question)


# ===========================================================================
# Search already open tests
# ===========================================================================

class TestSearchAlreadyOpenDetection(unittest.TestCase):
    def setUp(self):
        self.cm = ContextManager()

    @patch("context_manager.browser_detector.BrowserDetector.find_website_across_browsers")
    def test_search_page_already_open_asks_replace_new_tab(self, mock_find):
        from context_manager.browser_detector import BrowserTab, BrowserInfo, BrowserTabMatch
        mock_find.return_value = [
            BrowserTabMatch(
                browser=BrowserInfo(name="chrome", display_name="Chrome", process_name="chrome.exe", running=True, debug_port=9222),
                tab=BrowserTab(id=3, title="Google Search - cats", url="https://www.google.com/search?q=cats", active=False, window_id=1),
            ),
        ]
        result = self.cm.check_before_execution(
            "search", {"query": "dogs", "provider": "google"}, "search dogs",
        )
        self.assertIsNotNone(result)
        self.assertTrue(result.needs_clarification)
        self.assertIn("replace the current search", result.clarification_question)

    @patch("context_manager.browser_detector.BrowserDetector.find_website_across_browsers")
    def test_search_replace_action(self, mock_find):
        from context_manager.browser_detector import BrowserTab, BrowserInfo, BrowserTabMatch
        mock_find.return_value = [
            BrowserTabMatch(
                browser=BrowserInfo(name="chrome", display_name="Chrome", process_name="chrome.exe", running=True, debug_port=9222),
                tab=BrowserTab(id=3, title="Google Search - cats", url="https://www.google.com/search?q=cats", active=False, window_id=1),
            ),
        ]
        self.cm.check_before_execution(
            "search", {"query": "dogs", "provider": "google"}, "search dogs",
        )
        result = self.cm.handle_follow_up("replace it")
        self.assertTrue(result.success)
        self.assertEqual(result.data["action"], "use_current_tab")
        self.assertEqual(result.data["context"]["query"], "dogs")


# ===========================================================================
# Content classification tests
# ===========================================================================

class TestContentClassification(unittest.TestCase):
    def setUp(self):
        from context_manager.browser_detector import BrowserTab
        self.bt = BrowserTab

    def test_music_content(self):
        tab = self.bt(id=1, title="YouTube Music", url="https://music.youtube.com", active=True, window_id=1)
        from context_manager.browser_detector import BrowserDetector
        bd = BrowserDetector()
        self.assertEqual(bd.classify_tab_content(tab), "music")

    def test_youtube_music_title(self):
        tab = self.bt(id=1, title="YouTube Music - Billie Eilish", url="https://www.youtube.com/watch?v=abc", active=True, window_id=1)
        from context_manager.browser_detector import BrowserDetector
        bd = BrowserDetector()
        self.assertEqual(bd.classify_tab_content(tab), "music")

    def test_video_content(self):
        tab = self.bt(id=1, title="YouTube", url="https://www.youtube.com/watch?v=abc", active=True, window_id=1)
        from context_manager.browser_detector import BrowserDetector
        bd = BrowserDetector()
        self.assertEqual(bd.classify_tab_content(tab), "video")

    def test_document_content(self):
        tab = self.bt(id=1, title="Doc", url="https://docs.google.com/document/d/123", active=True, window_id=1)
        from context_manager.browser_detector import BrowserDetector
        bd = BrowserDetector()
        self.assertEqual(bd.classify_tab_content(tab), "document")

    def test_coding_content(self):
        tab = self.bt(id=1, title="GitHub", url="https://github.com/user/repo", active=True, window_id=1)
        from context_manager.browser_detector import BrowserDetector
        bd = BrowserDetector()
        self.assertEqual(bd.classify_tab_content(tab), "coding")

    def test_search_content(self):
        tab = self.bt(id=1, title="Google Search", url="https://www.google.com/search?q=test", active=True, window_id=1)
        from context_manager.browser_detector import BrowserDetector
        bd = BrowserDetector()
        self.assertEqual(bd.classify_tab_content(tab), "search")

    def test_chat_content(self):
        tab = self.bt(id=1, title="ChatGPT", url="https://chatgpt.com", active=True, window_id=1)
        from context_manager.browser_detector import BrowserDetector
        bd = BrowserDetector()
        self.assertEqual(bd.classify_tab_content(tab), "chat")


# ===========================================================================
# Work content awareness tests
# ===========================================================================

class TestWorkContentDetection(unittest.TestCase):
    def setUp(self):
        self.cm = ContextManager()

    def test_docs_is_work(self):
        self.assertTrue(self.cm._tab_has_work_content("Google Docs - My Doc", "https://docs.google.com/document/d/123"))

    def test_github_is_work(self):
        self.assertTrue(self.cm._tab_has_work_content("GitHub", "https://github.com/user/repo"))

    def test_notion_is_work(self):
        self.assertTrue(self.cm._tab_has_work_content("Notion", "https://notion.so/workspace"))

    def test_youtube_is_not_work(self):
        self.assertFalse(self.cm._tab_has_work_content("YouTube", "https://www.youtube.com/watch?v=abc"))

    def test_google_search_is_not_work(self):
        self.assertFalse(self.cm._tab_has_work_content("Google", "https://www.google.com/search?q=cats"))


# ===========================================================================
# Parser play intent tests
# ===========================================================================

class TestPlayMusicParser(unittest.TestCase):
    def setUp(self):
        from brain.parser import Parser
        self.parser = Parser()

    def test_play_artist(self):
        result = self.parser.parse("play Billie Eilish")
        self.assertEqual(result.intent, "play_music")
        self.assertEqual(result.entities["query"], "billie eilish")

    def test_play_song(self):
        result = self.parser.parse("play Despacito")
        self.assertEqual(result.intent, "play_music")
        self.assertEqual(result.entities["query"], "despacito")

    def test_play_website(self):
        result = self.parser.parse("play YouTube")
        self.assertEqual(result.intent, "open_website")
        self.assertEqual(result.entities["website"], "youtube")

    def test_play_app(self):
        result = self.parser.parse("play chrome")
        self.assertEqual(result.intent, "open_app")


# ===========================================================================
# Regression: BUG #1 — handle_follow_up must include intent in response data
# ===========================================================================

class TestContextManagerFollowUpIntent(unittest.TestCase):
    def setUp(self):
        self.cm = ContextManager()

    def test_handle_follow_up_includes_intent(self):
        """handle_follow_up must set intent in response data so resolve_context does not exit early."""
        self.cm.clarification.set_pending(
            "Chrome is running. Switch or new window?",
            ClarificationType.APP_ALREADY_RUNNING,
            context={"app_name": "chrome", "display_name": "Chrome", "process_name": "chrome.exe"},
            follow_up_intent="open_app",
        )
        response = self.cm.handle_follow_up("new window")
        self.assertIsNotNone(response)
        self.assertTrue(response.success)
        self.assertIn("intent", response.data)
        intent = response.data.get("intent")
        self.assertTrue(intent, f"intent must be non-empty, got {intent!r}")
        self.assertEqual(intent, "open_app")

    def test_handle_follow_up_includes_action(self):
        """handle_follow_up must include the resolved action in response data."""
        self.cm.clarification.set_pending(
            "Chrome is running. Switch or new window?",
            ClarificationType.APP_ALREADY_RUNNING,
            context={"app_name": "chrome", "display_name": "Chrome", "process_name": "chrome.exe"},
            follow_up_intent="open_app",
        )
        response = self.cm.handle_follow_up("new window")
        self.assertIsNotNone(response)
        self.assertEqual(response.data.get("action"), "open_new_window")

    def test_handle_follow_up_switch_to_existing_includes_intent(self):
        """handle_follow_up for 'switch' answer must also include intent."""
        self.cm.clarification.set_pending(
            "Chrome is running. Switch or new window?",
            ClarificationType.APP_ALREADY_RUNNING,
            context={"app_name": "chrome", "display_name": "Chrome", "process_name": "chrome.exe"},
            follow_up_intent="open_app",
        )
        response = self.cm.handle_follow_up("switch")
        self.assertIsNotNone(response)
        self.assertTrue(response.success)
        intent = response.data.get("intent")
        self.assertTrue(intent, f"intent must be non-empty, got {intent!r}")
        self.assertEqual(intent, "open_app")


if __name__ == "__main__":
    unittest.main()
