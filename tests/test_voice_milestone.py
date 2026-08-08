"""
tests/test_voice_milestone.py

Milestone: Voice pipeline rebuild.

Verifies the four behaviours the rebuild ships:

  1. ASR confidence is preserved end-to-end: Speech -> Brain -> Pipeline ->
     Response (never dropped at the brain boundary).
  2. Low-confidence speech is rejected by the safety gate before it reaches
     the executor, and uncertain speech hedges the generated wording.
  3. ``_run_command`` forwards speech_confidence into the brain and ALWAYS
     returns the backend to Idle (no lingering LISTENING).
  4. Every required milestone command returns a terminal response through
     the rule pipeline (no reasoner / no LLM required).

No browser, mic, or real TTS is touched: everything is mocked.
"""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock

from brain.parser import Parser
from brain.planner import Planner
from models.response import Response
from models.task_result import TaskResult
from run import _run_command
from services.conversation_manager import ConversationManager
from tasks.task_manager import TaskManager
from thinking.pipeline import PipelineEngine
from thinking.reasoner import ReasonedPlan
from thinking.utterance_classifier import ClassificationResult, UtteranceCategory, UtteranceClassifier


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
    def __init__(self, plans=None) -> None:
        self._plans = list(plans or [])

    def reason(self, text, memory=None, world_state=None, awareness=None):  # noqa: ARG002
        return self._plans.pop(0) if self._plans else None

    def continue_(self, original_text, question, answer, memory=None, world_state=None, awareness=None):  # noqa: ARG002
        return None


class _QuestionOnlyClassifier:
    """Delegates action commands to the real rule fast-path (no LLM) but
    answers trailing questions deterministically so the test never waits on
    a language model."""

    def __init__(self) -> None:
        self._real = UtteranceClassifier()

    def classify(self, text: str) -> ClassificationResult:
        if text.strip().endswith("?"):
            return ClassificationResult(
                category=UtteranceCategory.QUESTION,
                response="I don't know yet.",
                source="stub",
            )
        return self._real.classify(text)


class _StubWorld:
    """Minimal world-model stand-in so the Intelligent Planner's
    verification checks observe a healthy state."""

    def app_running(self, name):  # noqa: ARG002
        return True

    @property
    def browsers(self) -> dict:
        return {}

    @property
    def video_playing(self) -> bool:
        return True


class _StubWorldState:
    def current(self) -> _StubWorld:
        return _StubWorld()


def _pipeline(reasoner=None, executor=None, classifier=None, world_state=None) -> PipelineEngine:
    return PipelineEngine(
        parser=Parser(),
        planner=Planner(),
        executor=executor or FakeExecutor(),
        reasoner=reasoner,
        utterance_classifier=classifier,
        world_state=world_state,
    )


class TestSpeechConfidenceFlow(unittest.TestCase):
    def test_reasoned_act_carries_speech_confidence(self) -> None:
        executor = FakeExecutor([Response(success=True, message="Switched to Chrome.", data={})])
        reasoner = FakeReasoner([
            ReasonedPlan(
                mode="ACT", intent="focus_app", entities={"app_name": "chrome"},
                confidence=0.92, reasoning="wants chrome focused",
            ),
        ])
        response = _pipeline(reasoner=reasoner, executor=executor).process(
            "focus chrome", speech_confidence=0.93,
        )

        self.assertTrue(response.success)
        self.assertAlmostEqual(response.speech_confidence, 0.93)
        self.assertAlmostEqual(response.confidence, 0.92)
        self.assertEqual(len(executor.plans), 1)

    def test_rule_path_carries_speech_confidence(self) -> None:
        response = _pipeline(world_state=_StubWorldState()).process("open chrome", speech_confidence=0.9)

        self.assertTrue(response.success)
        self.assertAlmostEqual(response.speech_confidence, 0.9)

    def test_no_speech_confidence_stays_none(self) -> None:
        response = _pipeline(world_state=_StubWorldState()).process("open chrome")

        self.assertTrue(response.success)
        self.assertIsNone(response.speech_confidence)


class TestLowConfidenceHandling(unittest.TestCase):
    def test_below_reject_threshold_is_not_executed(self) -> None:
        executor = FakeExecutor()
        response = _pipeline(executor=executor).process("open chrome", speech_confidence=0.05)

        self.assertFalse(response.success)
        self.assertAlmostEqual(response.speech_confidence, 0.05)
        self.assertEqual(executor.plans, [])
        self.assertIn("rejected", response.message.casefold())

    def test_uncertain_speech_hedges_the_response(self) -> None:
        executor = FakeExecutor([Response(success=True, message="done.", data={})])
        response = _pipeline(executor=executor, world_state=_StubWorldState()).process(
            "open chrome", speech_confidence=0.35,
        )

        self.assertTrue(response.success)
        self.assertEqual(len(executor.plans), 1)
        self.assertIn("not fully sure", response.message.casefold())

    def test_confident_speech_does_not_hedge(self) -> None:
        executor = FakeExecutor([Response(success=True, message="done.", data={})])
        response = _pipeline(executor=executor, world_state=_StubWorldState()).process(
            "open chrome", speech_confidence=0.9,
        )

        self.assertTrue(response.success)
        self.assertNotIn("not fully sure", response.message.casefold())


class TestRunCommandForwardsSpeechConfidence(unittest.TestCase):
    def test_forwards_confidence_and_returns_to_idle(self) -> None:
        captured = {}

        def brain_process(text, cancel_event=None, confirmed=False, speech_confidence=None, **kwargs):  # noqa: ARG002
            captured["speech_confidence"] = speech_confidence
            return Response(success=True, message="Done.", task_result=TaskResult.SUCCESS)

        bridge = MagicMock()
        brain = MagicMock()
        brain.process = brain_process
        tm = TaskManager()
        cm = ConversationManager()
        response_manager = MagicMock()
        response_manager._voice_enabled = False
        response_manager.console_text.return_value = "subtitle"
        voice_engine = MagicMock()
        voice_engine.is_speaking = False
        voice_engine.queue_size = 0
        voice_engine.is_busy = False
        wake_word_service = MagicMock()
        microphone_stream = MagicMock()
        watchdog_manager = MagicMock()

        response = _run_command(
            bridge, brain, tm, cm, response_manager, voice_engine,
            wake_word_service, microphone_stream, watchdog_manager,
            "open chrome", speech_confidence=0.88,
        )

        self.assertIsNotNone(response)
        self.assertAlmostEqual(captured["speech_confidence"], 0.88)
        bridge.set_core_state.assert_any_call("idle")
        self.assertIsNone(tm.active_task)


class TestRequiredCommands(unittest.TestCase):
    _COMMANDS = [
        "open chrome",
        "open notepad",
        "open calculator",
        "play music",
        "what time is it?",
        "what apps are running?",
    ]

    def test_all_commands_return_a_terminal_response(self) -> None:
        pipeline = _pipeline(classifier=_QuestionOnlyClassifier(), world_state=_StubWorldState())

        for command in self._COMMANDS:
            with self.subTest(command=command):
                response = pipeline.process(command, speech_confidence=0.9)
                self.assertIsNotNone(response)
                self.assertTrue(response.message.strip())

    def test_action_commands_reach_the_executor(self) -> None:
        executor = FakeExecutor()
        pipeline = _pipeline(
            executor=executor,
            classifier=_QuestionOnlyClassifier(),
            world_state=_StubWorldState(),
        )

        for command in ["open chrome", "open notepad", "open calculator", "play music"]:
            with self.subTest(command=command):
                executor.plans.clear()
                response = pipeline.process(command, speech_confidence=0.9)
                self.assertIsNotNone(response)
                self.assertEqual(len(executor.plans), 1, f"{command!r} should reach the executor")
                self.assertTrue(response.message.strip())


if __name__ == "__main__":
    unittest.main()
