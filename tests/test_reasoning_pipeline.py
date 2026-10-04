"""
tests/test_reasoning_pipeline.py

Integration tests for the reasoning gate wired into PipelineEngine:

  1. ACT routes through the deterministic stages and carries confidence.
  2. ANSWER is returned directly, never touching the executor.
  3. ASK stores a pending reasoner question; the answer is re-reasoned.
  4. Auto-retry ONCE with an alternative strategy on failure.
  5. When the retry also fails, the response explains + asks (no looping).
  6. reasoner=None / unreachable falls back to the rule pipeline untouched.
"""

from __future__ import annotations

import unittest

from brain.parser import Parser
from brain.planner import Planner
from models.response import Response
from thinking.pipeline import PipelineEngine
from thinking.reasoner import Alternative, ReasonedPlan


class FakeExecutor:
    def __init__(self, results=None) -> None:
        self._results = list(results or [])
        self.plans = []

    def execute(self, plan, cancel_event=None):  # noqa: ARG002
        self.plans.append(plan)
        if self._results:
            return self._results.pop(0)
        return Response(success=True, message="done.", data={})


class FakeReasoner:
    def __init__(self, plans=None, continue_plans=None) -> None:
        self._plans = list(plans or [])
        self._continue_plans = list(continue_plans or [])
        self.reason_calls = 0
        self.continue_calls = 0

    def reason(self, text, memory=None, world_state=None, awareness=None, budget=None):  # noqa: ARG002
        self.reason_calls += 1
        return self._plans.pop(0) if self._plans else None

    def continue_(self, original_text, question, answer, memory=None, world_state=None, awareness=None, budget=None):  # noqa: ARG002
        self.continue_calls += 1
        return self._continue_plans.pop(0) if self._continue_plans else None


def _pipeline(reasoner=None, executor=None) -> PipelineEngine:
    return PipelineEngine(
        parser=Parser(),
        planner=Planner(),
        executor=executor or FakeExecutor(),
        reasoner=reasoner,
    )


class TestReasonerActPath(unittest.TestCase):
    def test_act_routes_and_carries_confidence(self) -> None:
        executor = FakeExecutor([Response(success=True, message="Switched to Chrome.", data={})])
        reasoner = FakeReasoner([
            ReasonedPlan(
                mode="ACT", intent="focus_app", entities={"app_name": "chrome"},
                confidence=0.92, reasoning="wants chrome focused",
            ),
        ])
        # Use a command the deterministic parser won't handle
        response = _pipeline(reasoner=reasoner, executor=executor).process("please focus my chrome window")

        self.assertTrue(response.success)
        self.assertEqual(len(executor.plans), 1)
        self.assertEqual(executor.plans[0].intent, "focus_app")
        self.assertAlmostEqual(response.confidence, 0.92)
        self.assertEqual(response.reasoning, "wants chrome focused")

    def test_answer_mode_never_touches_executor(self) -> None:
        executor = FakeExecutor()
        reasoner = FakeReasoner([
            ReasonedPlan(
                mode="ANSWER", intent="", confidence=0.8,
                answer="I'm JARVIS, your desktop assistant.",
            ),
        ])
        response = _pipeline(reasoner=reasoner, executor=executor).process("who are you")

        self.assertTrue(response.success)
        self.assertEqual(response.message, "I'm JARVIS, your desktop assistant.")
        self.assertEqual(executor.plans, [])

    def test_answer_mode_hedges_low_confidence(self) -> None:
        reasoner = FakeReasoner([
            ReasonedPlan(mode="ANSWER", intent="", confidence=0.3, answer="The sky is green."),
        ])
        response = _pipeline(reasoner=reasoner).process("what color is the sky")
        self.assertTrue(response.success)
        self.assertIn("not fully sure", response.message)

    def test_ask_mode_returns_clarification(self) -> None:
        reasoner = FakeReasoner([
            ReasonedPlan(
                mode="ASK", intent="open_app", confidence=0.5,
                question="Which app should I open?",
            ),
        ])
        pipeline = _pipeline(reasoner=reasoner)
        # Use a command the deterministic parser won't handle
        response = pipeline.process("I want to open an application")

        self.assertTrue(response.needs_clarification)
        self.assertEqual(response.clarification_question, "Which app should I open?")
        self.assertTrue(pipeline.pending_clarification_exists)


class TestReasonerAskContinuation(unittest.TestCase):
    def test_answer_to_ask_reasons_into_act(self) -> None:
        executor = FakeExecutor([Response(success=True, message="done.", data={})])
        reasoner = FakeReasoner(
            plans=[ReasonedPlan(mode="ASK", intent="", confidence=0.5,
                                question="Which browser?")],
            continue_plans=[ReasonedPlan(
                mode="ACT", intent="focus_app", entities={"app_name": "chrome"},
                confidence=0.9, reasoning="user chose chrome",
            )],
        )
        pipeline = _pipeline(reasoner=reasoner, executor=executor)
        # Use a command the deterministic parser won't handle
        first = pipeline.process("I'd like to open the browser please")
        self.assertTrue(first.needs_clarification)

        response = pipeline.resolve_context("chrome")
        self.assertTrue(response.success)
        self.assertEqual(len(executor.plans), 1)
        self.assertEqual(executor.plans[0].intent, "focus_app")
        self.assertAlmostEqual(response.confidence, 0.9)
        self.assertEqual(response.reasoning, "user chose chrome")
        self.assertEqual(reasoner.continue_calls, 1)


class TestReasonerRetry(unittest.TestCase):
    def _retry_pipeline(self, executor, reasoner) -> PipelineEngine:
        from intelligence.world_state import BrowserState, WorldState

        class FakeWorldStateService:
            def current(self):
                return WorldState(
                    timestamp=0.0,
                    browsers={"chrome": BrowserState(
                        name="chrome", display_name="Chrome", running=True,
                        active_url="https://www.spotify.com/",
                    )},
                )

        return PipelineEngine(
            parser=Parser(), planner=Planner(), executor=executor,
            reasoner=reasoner, world_state=FakeWorldStateService(),
        )

    def test_auto_retries_once_with_alternative(self) -> None:
        executor = FakeExecutor([
            Response(success=False, message="App not installed.", data={}),
            Response(success=True, message="Opened in browser.", data={}),
        ])
        reasoner = FakeReasoner([
            ReasonedPlan(
                mode="ACT", intent="open_app", entities={"app_name": "myapp"},
                confidence=0.9,
                alternatives=[Alternative(
                    intent="open_website", entities={"website": "myapp.com"},
                    description="open in browser",
                )],
            ),
        ])
        response = self._retry_pipeline(executor, reasoner).process("launch myapp")

        self.assertTrue(response.success)
        self.assertEqual([p.intent for p in executor.plans], ["open_app", "open_website"])
        self.assertEqual(response.message, "Opened in browser.")

    def test_retry_fails_explains_and_asks(self) -> None:
        executor = FakeExecutor([
            Response(success=False, message="App not installed.", data={}),
            Response(success=False, message="The website didn't load.", data={}),
        ])
        reasoner = FakeReasoner([
            ReasonedPlan(
                mode="ACT", intent="open_app", entities={"app_name": "myapp"},
                confidence=0.9,
                alternatives=[Alternative(
                    intent="open_website", entities={"website": "myapp.com"},
                    description="open in browser",
                )],
            ),
        ])
        response = self._retry_pipeline(executor, reasoner).process("launch myapp")

        self.assertFalse(response.success)
        self.assertTrue(response.data.get("retry_attempted"))
        self.assertEqual(len(executor.plans), 2, "must retry exactly once, never loop")
        self.assertIn("alternative", response.message)
        self.assertIn("?", response.message)


class TestReasonerFallback(unittest.TestCase):
    def test_no_reasoner_uses_rule_pipeline(self) -> None:
        executor = FakeExecutor([Response(success=True, message="done.", data={})])
        response = _pipeline(executor=executor).process("focus chrome")

        self.assertTrue(response.success)
        self.assertEqual(len(executor.plans), 1)
        self.assertEqual(executor.plans[0].intent, "focus_app")

    def test_reasoner_returns_none_falls_back(self) -> None:
        executor = FakeExecutor([Response(success=True, message="done.", data={})])
        reasoner = FakeReasoner([])  # reason() returns None
        # Use a command the deterministic parser won't handle
        response = _pipeline(reasoner=reasoner, executor=executor).process("please focus my chrome window")

        self.assertTrue(response.success)
        self.assertEqual(len(executor.plans), 1)
        self.assertEqual(reasoner.reason_calls, 1)


class TestWorkingMemoryWiring(unittest.TestCase):
    def test_commands_recorded_in_working_memory(self) -> None:
        from working_memory import WorkingMemory

        executor = FakeExecutor([Response(success=True, message="done.", data={})])
        wm = WorkingMemory()
        wm.start()
        try:
            pipeline = PipelineEngine(
                parser=Parser(), planner=Planner(), executor=executor,
                working_memory=wm,
            )
            pipeline.process("focus chrome")
            recent = [e.content for e in wm.get_recent_commands(limit=5)]
            self.assertTrue(any("focus chrome" in c for c in recent))
        finally:
            wm.stop()


if __name__ == "__main__":
    unittest.main()

