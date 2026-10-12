"""
tests/test_voice_milestone.py

Milestone: Voice pipeline rebuild.

Verifies the four behaviours the rebuild ships:

  1. ASR confidence is preserved end-to-end: Speech -> Brain -> Pipeline ->
     Response (never dropped at the brain boundary).
  2. Low-confidence speech is rejected by the safety gate before it reaches
     the executor, and uncertain speech hedges the generated wording.
  3. ``ConversationOwner._run_command`` forwards speech_confidence into the
     brain and leaves the turn in a valid, non-stuck state with the task
     finalized (the owner loop advances the state machine afterwards).
  4. Every required milestone command returns a terminal response through
     the rule pipeline (no reasoner / no LLM required).

No browser, mic, or real TTS is touched: everything is mocked.
"""

from __future__ import annotations

import queue
import threading
import unittest
from unittest.mock import MagicMock

from brain.parser import Parser
from brain.planner import Planner
from models.response import Response
from models.task_result import TaskResult
from services.conversation_manager import ConversationManager, ConversationState
from services.conversation_owner import ConversationOwner
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
        self.calls: list[str] = []

    def reason(self, text, memory=None, world_state=None, awareness=None, budget=None):  # noqa: ARG002
        self.calls.append(text)
        return self._plans.pop(0) if self._plans else None

    def continue_(self, original_text, question, answer, memory=None, world_state=None, awareness=None, budget=None):  # noqa: ARG002
        return None


class _QuestionOnlyClassifier:
    """Delegates action commands to the real rule fast-path (no LLM) but
    answers trailing questions deterministically so the test never waits on
    a language model."""

    def __init__(self) -> None:
        self._real = UtteranceClassifier()

    def classify(self, text: str, time_budget=None) -> ClassificationResult:  # noqa: ARG002
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
    # Gate 0c (the deterministic local-command dictionary) resolves
    # "open/focus <app>" without the LLM, so it can no longer be used to
    # exercise the reasoner path.  This request is deliberately outside that
    # dictionary.
    _REASONER_ONLY_REQUEST = "reorganise my study notes into topics"

    def test_reasoned_act_carries_speech_confidence(self) -> None:
        executor = FakeExecutor([Response(success=True, message="Switched to Chrome.", data={})])
        reasoner = FakeReasoner([
            ReasonedPlan(
                mode="ACT", intent="focus_app", entities={"app_name": "chrome"},
                confidence=0.92, reasoning="wants chrome focused",
            ),
        ])
        response = _pipeline(
            reasoner=reasoner, executor=executor, world_state=_StubWorldState(),
        ).process(self._REASONER_ONLY_REQUEST, speech_confidence=0.93)

        # The turn must genuinely have gone through the reasoner.
        self.assertEqual(reasoner.calls, [self._REASONER_ONLY_REQUEST])
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
        self.assertEqual(executor.plans, [], "a rejected utterance must not execute")
        # The user hears an honest "didn't catch that", never a status code.
        self.assertIn("didn't catch", response.message.casefold())

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


def _make_owner(**overrides) -> ConversationOwner:
    """Build a ConversationOwner whose collaborators are mocks.

    ``TaskManager`` and ``ConversationManager`` stay real because the
    lifecycle invariants under test live in those two components.
    """
    collaborators = {
        "conversation_manager": ConversationManager(),
        "bridge": MagicMock(),
        "brain": MagicMock(),
        "task_manager": TaskManager(),
        "response_manager": MagicMock(),
        "voice_engine": MagicMock(),
        "wake_word_service": MagicMock(),
        "microphone_stream": MagicMock(),
        "duplex_session": MagicMock(),
        "command_queue": queue.Queue(),
        "wake_word_detected": threading.Event(),
        "watchdog_manager": MagicMock(),
        "service_manager": MagicMock(),
        "shutdown_in_progress": threading.Event(),
        "shutdown_event": threading.Event(),
        "wake_word_enabled": True,
    }
    collaborators.update(overrides)
    return ConversationOwner(**collaborators)


class TestRunCommandForwardsSpeechConfidence(unittest.TestCase):
    def test_forwards_confidence_and_finalizes_the_turn(self) -> None:
        captured = {}

        def brain_process(text, cancel_event=None, confirmed=False, speech_confidence=None, **kwargs):  # noqa: ARG002
            captured["text"] = text
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

        owner = _make_owner(
            bridge=bridge,
            brain=brain,
            task_manager=tm,
            conversation_manager=cm,
            response_manager=response_manager,
            voice_engine=voice_engine,
        )

        response = owner._run_command("open chrome", speech_confidence=0.88)

        self.assertIsNotNone(response)
        self.assertEqual(captured["text"], "open chrome")
        self.assertAlmostEqual(captured["speech_confidence"], 0.88)
        # The command is finalized: no lingering active task.
        self.assertIsNone(tm.active_task)
        # The turn ends in a valid, non-stuck state.  Advancing to
        # ACTIVE_CONVERSATION is the owner loop's job (Requirement #9).
        self.assertIn(
            cm.state,
            (ConversationState.THINKING, ConversationState.ACTIVE_CONVERSATION),
        )

    def test_brain_failure_still_finalizes_the_turn(self) -> None:
        """A failed command must not leave the task RUNNING or the turn wedged."""
        brain = MagicMock()
        brain.process.side_effect = RuntimeError("provider exploded")
        tm = TaskManager()
        cm = ConversationManager()
        response_manager = MagicMock()
        response_manager._voice_enabled = False
        response_manager.console_text.return_value = "subtitle"

        owner = _make_owner(
            brain=brain, task_manager=tm, conversation_manager=cm,
            response_manager=response_manager,
        )

        response = owner._run_command("open chrome")

        self.assertIsNone(response)
        self.assertIsNone(tm.active_task)
        self.assertEqual(cm.state, ConversationState.THINKING)
        # Recovery is the caller's job (_run_command_safe returns to idle).
        self.assertFalse(owner._shutdown_in_progress.is_set())

    def test_refusal_path_finalizes_no_task(self) -> None:
        """A refused utterance speaks the refusal and executes nothing."""
        brain = MagicMock()
        tm = TaskManager()
        cm = ConversationManager()
        response_manager = MagicMock()
        response_manager._voice_enabled = False
        voice_engine = MagicMock()
        voice_engine.is_busy = False

        owner = _make_owner(
            brain=brain, task_manager=tm, conversation_manager=cm,
            response_manager=response_manager, voice_engine=voice_engine,
        )

        response = owner._run_command("huh", speech_confidence=0.02)

        self.assertIsNone(response)
        brain.process.assert_not_called()
        self.assertIsNone(tm.active_task)
        self.assertEqual(cm.state, ConversationState.SPEAKING)


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
