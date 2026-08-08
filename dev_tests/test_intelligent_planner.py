import time
import unittest
from unittest.mock import MagicMock

from brain.execution_plan import ExecutionPlan, Step
from brain.parser import Parser
from intelligence.intelligent_planner import (
    IntelligentPlanner,
    PlanResult,
    UserChoice,
    VerificationCheck,
)
from intelligence.world_state import (
    AppWindowState,
    BrowserState,
    BrowserWindowState,
    WorldState,
)


def _world(browsers=None, apps=(), video=False, active_website=None):
    return WorldState(
        timestamp=time.time(),
        applications=list(apps),
        browsers=dict(browsers or {}),
        video_playing=video,
        active_website=active_website,
    )


def _chrome_windows(n, url="https://google.com", content="web", playing=False):
    return BrowserState(
        name="chrome", display_name="Chrome", running=True,
        windows=[BrowserWindowState(i, 2) for i in range(n)],
        active_url=url, content=content, playing=playing,
    )


class TestVerificationSpec(unittest.TestCase):
    def setUp(self):
        self.planner = IntelligentPlanner()
        self.parser = Parser()

    def test_open_app_verifies_app_running(self):
        parsed = self.parser.parse("open notepad")
        r = self.planner.create_plan(parsed, world_state=_world())
        self.assertEqual([c.kind for c in r.verification], ["app_running"])
        self.assertEqual(r.verification[0].target, "notepad")

    def test_close_app_verifies_app_closed(self):
        parsed = self.parser.parse("close notepad")
        r = self.planner.create_plan(parsed, world_state=_world())
        self.assertEqual([c.kind for c in r.verification], ["app_closed"])

    def test_open_website_verifies_url_loaded(self):
        parsed = self.parser.parse("open youtube")
        r = self.planner.create_plan(parsed, world_state=_world())
        self.assertEqual(r.verification[0].kind, "url_loaded")

    def test_play_music_verifies_media_playing(self):
        parsed = self.parser.parse("play some music")
        r = self.planner.create_plan(parsed, world_state=_world())
        self.assertEqual(r.verification[0].kind, "media_playing")

    def test_plan_metadata_contains_verification(self):
        parsed = self.parser.parse("open notepad")
        r = self.planner.create_plan(parsed, world_state=_world())
        self.assertTrue(r.plan.metadata["intelligent"])
        self.assertEqual(len(r.plan.metadata["verification"]), 1)


class TestUserChoiceDetection(unittest.TestCase):
    def setUp(self):
        self.planner = IntelligentPlanner()
        self.parser = Parser()

    def test_close_app_multiple_windows_asks(self):
        parsed = self.parser.parse("close chrome")
        r = self.planner.create_plan(
            parsed, world_state=_world(browsers={"chrome": _chrome_windows(2)})
        )
        self.assertIsNotNone(r.user_choice)
        self.assertEqual(r.user_choice.kind, "close_window_choice")
        self.assertIn("current window", r.user_choice.question.casefold())

    def test_close_app_single_window_no_ask(self):
        parsed = self.parser.parse("close chrome")
        r = self.planner.create_plan(
            parsed, world_state=_world(browsers={"chrome": _chrome_windows(1)})
        )
        self.assertIsNone(r.user_choice)

    def test_play_music_while_video_playing_asks(self):
        parsed = self.parser.parse("play billie eilish")
        r = self.planner.create_plan(
            parsed,
            world_state=_world(
                browsers={"chrome": _chrome_windows(1, "https://youtube.com/watch?v=x", "video", True)},
                video=True,
            ),
        )
        self.assertIsNotNone(r.user_choice)
        self.assertEqual(r.user_choice.kind, "music_replace")
        self.assertIn("already playing", r.user_choice.question.casefold())

    def test_no_choice_when_confirmed(self):
        parsed = self.parser.parse("close chrome")
        r = self.planner.create_plan(
            parsed, confirmed=True,
            world_state=_world(browsers={"chrome": _chrome_windows(2)}),
        )
        self.assertIsNone(r.user_choice)


class TestIntelligentRewrites(unittest.TestCase):
    def test_new_browser_window_becomes_focus_and_ctrl_n(self):
        planner = IntelligentPlanner()
        parser = Parser()
        parsed = parser.parse("open chrome")
        base = ExecutionPlan(
            raw_text="open chrome", intent="open_app", confidence=1.0,
            steps=[Step("open_app", "chrome", {"new_window": True, "app_name": "chrome"}, "New window")],
            metadata={},
        )
        r = planner.refine(
            base, parsed,
            world_state=_world(browsers={"chrome": _chrome_windows(1)}),
        )
        actions = [s.action for s in r.plan.steps]
        self.assertEqual(actions, ["focus_app", "hotkey"])
        self.assertEqual(r.plan.steps[1].parameters["keys"], "ctrl+n")

    def test_new_browser_window_launches_when_not_running(self):
        planner = IntelligentPlanner()
        parser = Parser()
        parsed = parser.parse("open chrome")
        base = ExecutionPlan(
            raw_text="open chrome", intent="open_app", confidence=1.0,
            steps=[Step("open_app", "chrome", {"new_window": True, "app_name": "chrome"}, "New window")],
            metadata={},
        )
        r = planner.refine(base, parsed, world_state=_world())
        self.assertEqual([s.action for s in r.plan.steps], ["open_app"])


class TestChoicePlanResolution(unittest.TestCase):
    def setUp(self):
        self.planner = IntelligentPlanner()
        self.parser = Parser()

    def test_close_all_windows(self):
        parsed = self.parser.parse("close chrome")
        choice = UserChoice(
            kind="close_window_choice",
            question="Close the current window or all of them?",
            options=["Current window", "All windows"],
            context={"browser": "chrome"},
        )
        plan = self.planner.build_choice_plan(choice, "all windows", parsed)
        self.assertEqual(plan.intent, "close_app")

    def test_close_current_window_uses_alt_f4(self):
        parsed = self.parser.parse("close chrome")
        choice = UserChoice(
            kind="close_window_choice",
            question="Close the current window or all of them?",
            options=["Current window", "All windows"],
            context={"browser": "chrome"},
        )
        plan = self.planner.build_choice_plan(choice, "current window", parsed)
        self.assertEqual(plan.steps[-1].parameters["keys"], "alt+f4")

    def test_replace_music(self):
        parsed = self.parser.parse("play billie eilish")
        choice = UserChoice(
            kind="music_replace",
            question="Do you want me to replace it?",
            options=["Replace", "Keep"],
            context={"browser": "chrome"},
        )
        plan = self.planner.build_choice_plan(choice, "replace", parsed)
        self.assertEqual(plan.intent, "play_music")

    def test_keep_music_is_noop(self):
        parsed = self.parser.parse("play billie eilish")
        choice = UserChoice(
            kind="music_replace",
            question="Do you want me to replace it?",
            options=["Replace", "Keep"],
            context={"browser": "chrome"},
        )
        plan = self.planner.build_choice_plan(choice, "keep", parsed)
        self.assertTrue(plan.metadata.get("noop"))

    def test_unmatched_answer_is_none(self):
        parsed = self.parser.parse("close chrome")
        choice = UserChoice(
            kind="close_window_choice",
            question="Close the current window or all of them?",
            options=["Current window", "All windows"],
            context={"browser": "chrome"},
        )
        self.assertIsNone(self.planner.build_choice_plan(choice, "wibble", parsed))


class TestPlayMusicFlow(unittest.TestCase):
    def setUp(self):
        self.planner = IntelligentPlanner()
        self.parser = Parser()

    def test_play_music_gets_click_first_video_step(self):
        parsed = self.parser.parse("play billie eilish")
        r = self.planner.create_plan(parsed, world_state=_world())
        actions = [s.action for s in r.plan.steps]
        self.assertEqual(actions, ["search", "click_first_video"])
        click_step = r.plan.steps[1]
        self.assertEqual(click_step.parameters["query"], "billie eilish")
        self.assertEqual(click_step.target, "billie eilish")

    def test_play_some_music_gets_click_first_video_step(self):
        parsed = self.parser.parse("play some music")
        r = self.planner.create_plan(parsed, world_state=_world())
        self.assertEqual([s.action for s in r.plan.steps], ["search", "click_first_video"])

    def test_play_flow_keeps_media_verification(self):
        parsed = self.parser.parse("play billie eilish")
        r = self.planner.create_plan(parsed, world_state=_world())
        self.assertEqual([c.kind for c in r.verification], ["media_playing"])

    def test_refine_appends_click_step_to_resolved_plan(self):
        parsed = self.parser.parse("play billie eilish")
        base = ExecutionPlan(
            raw_text="play billie eilish", intent="play_music", confidence=1.0,
            steps=[Step("search", None, {"query": "billie eilish", "provider": "youtube"}, "s")],
            metadata={},
        )
        r = self.planner.refine(base, parsed, world_state=_world())
        self.assertEqual([s.action for s in r.plan.steps], ["search", "click_first_video"])

    def test_non_youtube_search_unchanged(self):
        parsed = self.parser.parse("search hello")
        r = self.planner.create_plan(parsed, world_state=_world())
        self.assertEqual([s.action for s in r.plan.steps], ["search"])


class TestTaskResultStatusMapping(unittest.TestCase):
    def test_handler_status_maps_to_new_statuses(self):
        from models.action_result import ActionResult
        from models.task_result import TaskResult

        self.assertEqual(
            ActionResult.from_handler({"success": True, "status": "retrying"}).task_result,
            TaskResult.RETRYING,
        )
        self.assertEqual(
            ActionResult.from_handler({"success": True, "status": "waiting"}).task_result,
            TaskResult.WAITING,
        )
        self.assertEqual(
            ActionResult.from_handler({"success": False, "status": "user_confirmation"}).task_result,
            TaskResult.USER_CONFIRMATION,
        )
        self.assertEqual(
            ActionResult.from_handler({"success": True}).task_result,
            TaskResult.SUCCESS,
        )
        self.assertEqual(
            ActionResult.from_handler({"success": False}).task_result,
            TaskResult.FAILED,
        )
        self.assertNotIn(
            "status",
            ActionResult.from_handler({"success": True, "status": "retrying"}).data,
        )


if __name__ == "__main__":
    unittest.main()
