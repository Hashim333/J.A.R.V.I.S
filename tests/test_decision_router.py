"""
tests/test_decision_router.py — Decision Engine (CORE-001).

The Decision Engine routes every user request into one of four categories
before any reasoning or automation occurs:

  * LOCAL_COMMAND            — immediate, no LLM
  * CONTEXT_AWARE_COMMAND    — World Model needed
  * AI_REASONING             — planner/LLM genuinely required
  * ONLINE_RESEARCH          — only when current information is needed

The router accepts raw text, ParsedCommand and RecognizedIntent requests,
and an optional WorldSnapshot/dict context.  Every route must carry the
reason it was chosen and be recorded in the decision history.
"""

from __future__ import annotations

import logging
import unittest

from brain.parsed_command import ParsedCommand
from brain.parser import Parser
from thinking.decision_router import DecisionRouter, ExecutionPlan, RouteCategory
from thinking.intent_recognizer import IntentRecognizer, RecognizedIntent


class _WorldSnapshot:
    """Lightweight stand-in for world_model.model.WorldSnapshot."""

    def __init__(self) -> None:
        self.timestamp = 1.0


class TestLocalCommands(unittest.TestCase):
    def test_open_app_is_local(self) -> None:
        plan = DecisionRouter().route("open chrome")
        self.assertIs(plan.category, RouteCategory.LOCAL_COMMAND)
        self.assertTrue(plan.is_local)
        self.assertFalse(plan.needs_llm)
        self.assertFalse(plan.needs_world_model)
        self.assertEqual(plan.handler, "executor.local")

    def test_close_app_is_local(self) -> None:
        plan = DecisionRouter().route("close chrome")
        self.assertIs(plan.category, RouteCategory.LOCAL_COMMAND)

    def test_volume_control_is_local(self) -> None:
        for text in ("volume up", "increase volume", "mute", "set volume to 50"):
            plan = DecisionRouter().route(text)
            self.assertIs(
                plan.category, RouteCategory.LOCAL_COMMAND,
                f"{text!r} should be a local command",
            )

    def test_media_control_is_local(self) -> None:
        for text in ("pause the music", "next song", "resume playback"):
            plan = DecisionRouter().route(text)
            self.assertIs(
                plan.category, RouteCategory.LOCAL_COMMAND,
                f"{text!r} should be a local command",
            )

    def test_system_toggles_are_local(self) -> None:
        for text in ("screenshot", "lock the computer", "open settings",
                     "turn on wifi", "shut down the computer"):
            plan = DecisionRouter().route(text)
            self.assertIs(
                plan.category, RouteCategory.LOCAL_COMMAND,
                f"{text!r} should be a local command",
            )


class TestContextAwareCommands(unittest.TestCase):
    def test_focus_app_needs_world_model(self) -> None:
        plan = DecisionRouter().route("focus chrome")
        self.assertIs(plan.category, RouteCategory.CONTEXT_AWARE_COMMAND)
        self.assertTrue(plan.needs_world_model)
        self.assertFalse(plan.needs_llm)
        self.assertEqual(plan.handler, "planner.world_model")

    def test_plain_search_is_context_aware(self) -> None:
        plan = DecisionRouter().route("search google for python tutorial")
        self.assertIs(plan.category, RouteCategory.CONTEXT_AWARE_COMMAND)

    def test_open_website_is_context_aware(self) -> None:
        plan = DecisionRouter().route("open youtube")
        self.assertIs(plan.category, RouteCategory.CONTEXT_AWARE_COMMAND)

    def test_play_music_is_context_aware(self) -> None:
        plan = DecisionRouter().route("play some music")
        self.assertIs(plan.category, RouteCategory.CONTEXT_AWARE_COMMAND)

    def test_system_status_is_context_aware(self) -> None:
        plan = DecisionRouter().route("system status")
        self.assertIs(plan.category, RouteCategory.CONTEXT_AWARE_COMMAND)

    def test_close_all_apps_is_context_aware(self) -> None:
        plan = DecisionRouter().route("close all apps")
        self.assertIs(plan.category, RouteCategory.CONTEXT_AWARE_COMMAND)


class TestOnlineResearch(unittest.TestCase):
    def test_weather_search_is_online(self) -> None:
        plan = DecisionRouter().route("search for the weather in delhi")
        self.assertIs(plan.category, RouteCategory.ONLINE_RESEARCH)
        self.assertTrue(plan.needs_online)
        self.assertTrue(plan.needs_llm)
        self.assertEqual(plan.handler, "researcher")

    def test_news_marker_routes_unrecognised_to_online(self) -> None:
        plan = DecisionRouter().route("latest news on AI")
        self.assertIs(plan.category, RouteCategory.ONLINE_RESEARCH)

    def test_stock_price_query_is_online(self) -> None:
        plan = DecisionRouter().route("search bitcoin price")
        self.assertIs(plan.category, RouteCategory.ONLINE_RESEARCH)

    def test_plain_search_is_not_online(self) -> None:
        plan = DecisionRouter().route("search for python tutorial")
        self.assertNotEqual(plan.category, RouteCategory.ONLINE_RESEARCH)


class TestAIReasoning(unittest.TestCase):
    def test_unknown_utterance_is_ai_reasoning(self) -> None:
        plan = DecisionRouter().route("what is the capital of france")
        self.assertIs(plan.category, RouteCategory.AI_REASONING)
        self.assertTrue(plan.needs_llm)
        self.assertEqual(plan.handler, "reasoner")

    def test_question_without_current_info_marker_is_ai(self) -> None:
        plan = DecisionRouter().route("how do I fix a leaking tap")
        self.assertIs(plan.category, RouteCategory.AI_REASONING)

    def test_empty_or_none_request_is_ai(self) -> None:
        plan = DecisionRouter().route("")
        self.assertIs(plan.category, RouteCategory.AI_REASONING)
        plan_none = DecisionRouter().route(None)
        self.assertIs(plan_none.category, RouteCategory.AI_REASONING)


class TestRequestShapes(unittest.TestCase):
    def test_parsed_command_request(self) -> None:
        parsed = Parser().parse("open chrome")
        plan = DecisionRouter().route(parsed)
        self.assertIs(plan.category, RouteCategory.LOCAL_COMMAND)
        self.assertEqual(plan.intent, "open_app")
        self.assertEqual(plan.raw_text, "open chrome")

    def test_recognized_intent_request(self) -> None:
        parsed = Parser().parse("focus chrome")
        recognized: RecognizedIntent = IntentRecognizer().recognize(parsed)
        plan = DecisionRouter().route(recognized)
        self.assertIs(plan.category, RouteCategory.CONTEXT_AWARE_COMMAND)
        self.assertEqual(plan.intent, "focus_app")

    def test_context_dict_is_detected(self) -> None:
        plan = DecisionRouter().route("focus chrome", context={"active_app": "chrome"})
        self.assertTrue(plan.context_available)

    def test_world_snapshot_context(self) -> None:
        plan = DecisionRouter().route("focus chrome", context=_WorldSnapshot())
        self.assertTrue(plan.context_available)

    def test_missing_context_reported(self) -> None:
        plan = DecisionRouter().route("focus chrome", context=None)
        self.assertFalse(plan.context_available)


class TestRoutingReasons(unittest.TestCase):
    def test_local_reason_is_explicit(self) -> None:
        plan = DecisionRouter().route("open chrome")
        self.assertIn("local command", plan.reason)

    def test_online_reason_mentions_current_info(self) -> None:
        plan = DecisionRouter().route("search for the weather in delhi")
        self.assertIn("current information", plan.reason)

    def test_context_aware_reason_mentions_world_model(self) -> None:
        plan = DecisionRouter().route("focus chrome")
        self.assertIn("World Model", plan.reason)

    def test_ai_reason_mentions_reasoner(self) -> None:
        plan = DecisionRouter().route("what is the capital of france")
        self.assertIn("reasoner", plan.reason)

    def test_every_decision_is_logged(self) -> None:
        router = DecisionRouter()
        router.route("open chrome")
        router.route("focus chrome")
        router.route("search for the weather")
        history = router.decision_history
        self.assertEqual(len(history), 3)
        self.assertEqual(history[0]["category"], RouteCategory.LOCAL_COMMAND.value)
        self.assertEqual(history[1]["category"], RouteCategory.CONTEXT_AWARE_COMMAND.value)
        self.assertEqual(history[2]["category"], RouteCategory.ONLINE_RESEARCH.value)
        self.assertTrue(all("reason" in h and h["reason"] for h in history))

    def test_logging_emits_route_line(self) -> None:
        records: list[logging.LogRecord] = []
        handler = logging.Handler()
        handler.emit = records.append  # type: ignore[method-assign]
        logger = logging.getLogger("thinking.decision_router")
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)
        try:
            DecisionRouter().route("open chrome")
        finally:
            logger.removeHandler(handler)
        self.assertTrue(
            any("ROUTE LOCAL_COMMAND" in r.getMessage() for r in records),
            "expected a ROUTE log line",
        )


class TestExecutionPlanShape(unittest.TestCase):
    def test_plan_is_frozen_and_well_typed(self) -> None:
        plan = DecisionRouter().route("open chrome")
        self.assertIsInstance(plan, ExecutionPlan)
        self.assertEqual(plan.signals, ("deterministic_local_intent",))
        self.assertFalse(plan.needs_online)
        self.assertTrue(isinstance(plan.confidence, float))

    def test_signal_tagging(self) -> None:
        router = DecisionRouter()
        local = router.route("volume up")
        context = router.route("focus chrome")
        online = router.route("search for the weather")
        ai = router.route("what is a quantum computer")
        self.assertIn("deterministic_local_intent", local.signals)
        self.assertIn("requires_world_model_context", context.signals)
        self.assertIn("search_query_requests_current_info", online.signals)
        self.assertIn("no_safe_rule_path", ai.signals)


if __name__ == "__main__":
    unittest.main()
