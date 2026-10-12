"""
tests/test_duplicate_command_prevention.py

Regression tests for the "duplicate tabs / searches / simultaneous
commands" family of bugs:

  1. A plan may only run ONE tab-opening browser action per request —
     subsequent search/open_website steps are skipped.
  2. The Executor aborts a plan the moment its cancel_event is set
     (a new command cancelling the previous one).
  3. Two rapid commands yield exactly one active task; the first is
     cancelled and its cancel_event set.
  4. Superseding a task fires its cleanup callbacks (which cancel queued
     TTS) before the new response is spoken, and one response queues
     exactly one utterance (no overlapping / duplicate TTS).

No browser, mic, or real TTS is touched: everything is mocked.
"""

from __future__ import annotations

import queue
import threading
import unittest
from unittest.mock import MagicMock

from brain.execution_plan import ExecutionPlan, Step
from executor.executor import Executor
from executor.registry import Registry
from models.task_result import TaskResult
from services.conversation_manager import ConversationManager
from services.conversation_owner import ConversationOwner
from tasks.task_manager import TaskManager, TaskStatus


class _BrowserMock:
    """Records browser actions instead of touching pyautogui."""

    def __init__(self, calls: list[str]) -> None:
        self.calls = calls

    def run(self, step, voice_input=None):  # noqa: ARG002
        self.calls.append(step.action)
        return {"success": True, "message": f"ran {step.action}"}


class TestOneBrowserActionPerPlan(unittest.TestCase):
    def test_second_search_step_is_skipped(self) -> None:
        registry = Registry()
        calls: list[str] = []
        registry.register("search", _BrowserMock(calls))
        executor = Executor(registry)
        plan = ExecutionPlan(
            raw_text="search cats then dogs",
            intent="search",
            confidence=1.0,
            steps=[
                Step(action="search", parameters={"query": "cats", "provider": "google"}),
                Step(action="search", parameters={"query": "dogs", "provider": "google"}),
            ],
        )

        response = executor.execute(plan)

        self.assertTrue(response.success)
        self.assertEqual(calls, ["search"], "only the first search may run")

    def test_open_website_then_search_runs_one_action(self) -> None:
        registry = Registry()
        calls: list[str] = []
        registry.register("open_website", _BrowserMock(calls))
        registry.register("search", _BrowserMock(calls))
        executor = Executor(registry)
        plan = ExecutionPlan(
            raw_text="open youtube then search songs",
            intent="open_website",
            confidence=1.0,
            steps=[
                Step(action="open_website", parameters={"url": "youtube"}),
                Step(action="search", parameters={"query": "songs", "provider": "youtube"}),
            ],
        )

        response = executor.execute(plan)

        self.assertTrue(response.success)
        self.assertEqual(calls, ["open_website"])

    def test_single_browser_action_still_runs(self) -> None:
        registry = Registry()
        calls: list[str] = []
        registry.register("search", _BrowserMock(calls))
        executor = Executor(registry)
        plan = ExecutionPlan(
            raw_text="search cats",
            intent="search",
            confidence=1.0,
            steps=[Step(action="search", parameters={"query": "cats", "provider": "google"})],
        )

        response = executor.execute(plan)

        self.assertTrue(response.success)
        self.assertEqual(calls, ["search"])


class TestExecutorCancellation(unittest.TestCase):
    def test_cancel_event_aborts_before_any_step(self) -> None:
        registry = Registry()
        calls: list[str] = []
        registry.register("test_action", _BrowserMock(calls))
        executor = Executor(registry)
        cancel = threading.Event()
        cancel.set()
        plan = ExecutionPlan(
            raw_text="do thing",
            intent="test",
            confidence=1.0,
            steps=[Step(action="test_action")],
        )

        response = executor.execute(plan, cancel_event=cancel)

        self.assertEqual(response.task_result, TaskResult.CANCELLED)
        self.assertFalse(response.success)
        self.assertEqual(calls, [], "no step may run after cancellation")

    def test_cancel_event_aborts_between_steps(self) -> None:
        registry = Registry()

        class _CancelOnRun:
            def __init__(self, event: threading.Event) -> None:
                self._event = event
                self.runs = 0

            def run(self, step, voice_input=None):  # noqa: ARG002
                self.runs += 1
                self._event.set()
                return {"success": True, "message": "ok"}

        cancel = threading.Event()
        first = _CancelOnRun(cancel)
        second = _BrowserMock([])
        registry.register("action_a", first)
        registry.register("action_b", second)
        executor = Executor(registry)
        plan = ExecutionPlan(
            raw_text="a then b",
            intent="multi",
            confidence=1.0,
            steps=[Step(action="action_a"), Step(action="action_b")],
        )

        response = executor.execute(plan, cancel_event=cancel)

        self.assertEqual(response.task_result, TaskResult.CANCELLED)
        self.assertEqual(first.runs, 1)
        self.assertEqual(second.calls, [], "action_b must not run after cancel")
        self.assertEqual(response.message, "Operation cancelled.")

    def test_cancel_aborts_during_retry_loop(self) -> None:
        registry = Registry()

        class _RetryThenCancel:
            def __init__(self, event: threading.Event) -> None:
                self._event = event
                self.runs = 0

            def run(self, step, voice_input=None):  # noqa: ARG002
                self.runs += 1
                self._event.set()
                return {"success": False, "message": "retrying", "status": "RETRYING"}

        cancel = threading.Event()
        registry.register("action_a", _RetryThenCancel(cancel))
        executor = Executor(registry)
        plan = ExecutionPlan(
            raw_text="retry me",
            intent="multi",
            confidence=1.0,
            steps=[Step(action="action_a")],
        )

        response = executor.execute(plan, cancel_event=cancel)

        self.assertEqual(response.task_result, TaskResult.CANCELLED)


class TestRapidCommandsSingleActive(unittest.TestCase):
    def test_two_rapid_commands_yield_one_active_task(self) -> None:
        tm = TaskManager()
        first = tm.create_task("open chrome")
        second = tm.create_task("search cats on youtube")

        self.assertEqual(first.status, TaskStatus.CANCELLED)
        self.assertTrue(first.cancel_event.is_set(), "old task must signal its worker")
        self.assertTrue(second.is_active)
        self.assertEqual(len([t for t in [first, second] if t.is_active]), 1)

    def test_cancelled_task_aborts_running_executor(self) -> None:
        """The old task's cancel_event must abort a detached executor loop."""
        registry = Registry()

        class _GateHandler:
            def __init__(self, event: threading.Event) -> None:
                self._event = event
                self.runs = 0

            def run(self, step, voice_input=None):  # noqa: ARG002
                self.runs += 1
                # First run completes; the event fires between steps (as
                # when a new command cancels the task mid-plan).
                self._event.set()
                return {"success": True, "message": "ok"}

        tm = TaskManager()
        old_task = tm.create_task("open chrome")
        gate = _GateHandler(threading.Event())
        registry.register("gate", gate)
        executor = Executor(registry)
        plan = ExecutionPlan(
            raw_text="old command",
            intent="multi",
            confidence=1.0,
            steps=[Step(action="gate"), Step(action="gate")],
        )

        # Second command arrives while the first is still "running".
        tm.create_task("search cats on youtube")

        # A cancelled task's cancel_event is set — a detached executor that
        # tries to keep acting on it must abort before touching anything.
        response = executor.execute(plan, cancel_event=old_task.cancel_event)

        self.assertEqual(response.task_result, TaskResult.CANCELLED)
        self.assertEqual(gate.runs, 0, "the cancelled task must not keep acting")
        self.assertEqual(response.message, "Operation cancelled.")


def _make_owner(**overrides) -> ConversationOwner:
    """Build a ConversationOwner whose collaborators are mocks.

    ``TaskManager`` and ``ConversationManager`` stay real because the
    invariants under test live in those two components.
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


class TestDuplicateSpeechPrevention(unittest.TestCase):
    def test_superseding_a_task_cancels_queued_speech(self) -> None:
        """A new command must cancel the previous command's queued speech.

        This is the real duplicate-speech guard: the superseded task's
        cleanup callbacks run synchronously inside ``create_task`` — before
        the new response is generated or spoken — so two utterances can
        never overlap.
        """
        tm = TaskManager()
        voice_engine = MagicMock()
        owner = _make_owner(task_manager=tm, voice_engine=voice_engine)

        first = tm.create_task("open chrome")
        owner._register_task_cleanup(first)
        tm.start_task(first)

        second = tm.create_task("search cats on youtube")

        self.assertTrue(first.cancel_event.is_set())
        self.assertTrue(second.is_active)
        voice_engine.cancel_all.assert_called_once()
        voice_engine.stop_barge_in.assert_called_once()

    def test_present_response_speaks_the_response_exactly_once(self) -> None:
        """One response means exactly one queued utterance — never two."""
        bridge = MagicMock()
        response_manager = MagicMock()
        response_manager._voice_enabled = True
        response_manager.console_text.return_value = "subtitle"
        response_manager.voice_text.return_value = "Hello, I am JARVIS."
        voice_engine = MagicMock()
        owner = _make_owner(
            bridge=bridge,
            response_manager=response_manager,
            voice_engine=voice_engine,
        )

        class _Response:
            success = True
            task_result = None

        owner._present_response(_Response())

        bridge.show_subtitle.assert_called_once_with("subtitle")
        bridge.emit_speaking.assert_called_once()
        voice_engine.speak.assert_called_once()
        self.assertEqual(voice_engine.speak.call_args[0][0], "Hello, I am JARVIS.")

    def test_text_only_response_queues_no_speech(self) -> None:
        """A muted response manager must never queue speech."""
        response_manager = MagicMock()
        response_manager._voice_enabled = False
        voice_engine = MagicMock()
        owner = _make_owner(
            response_manager=response_manager, voice_engine=voice_engine,
        )

        class _Response:
            success = True
            task_result = None

        owner._present_response(_Response())

        voice_engine.speak.assert_not_called()


if __name__ == "__main__":
    unittest.main()
