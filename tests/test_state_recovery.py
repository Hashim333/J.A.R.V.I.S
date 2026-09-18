"""Regression tests for the UI/backend stuck in Listening/Thinking/Speaking bugs.

The single conversation owner is ``services.conversation_owner.ConversationOwner``
— it owns command execution and task finalization.
"""
from __future__ import annotations

import queue
import threading
import unittest
from unittest.mock import MagicMock

from models.response import Response
from models.task_result import TaskResult
from services.conversation_manager import ConversationManager, ConversationState
from services.conversation_owner import ConversationOwner
from tasks.task_manager import TaskManager, TaskStatus


class _PlaceholderResult:
    def __init__(self, value: str) -> None:
        self.value = value


def _make_owner(brain_process=None):
    bridge = MagicMock()
    brain = MagicMock()
    if brain_process is not None:
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
    owner = ConversationOwner(
        conversation_manager=cm,
        bridge=bridge,
        brain=brain,
        task_manager=tm,
        response_manager=response_manager,
        voice_engine=voice_engine,
        wake_word_service=MagicMock(),
        microphone_stream=MagicMock(),
        duplex_session=MagicMock(),
        command_queue=queue.Queue(),
        wake_word_detected=threading.Event(),
        watchdog_manager=MagicMock(),
        service_manager=MagicMock(),
        shutdown_in_progress=threading.Event(),
        shutdown_event=threading.Event(),
    )
    return owner, bridge, brain, tm, cm


class TestCommandOutcomeRecovery(unittest.TestCase):
    def test_brain_exception_finalizes_failed_and_returns_to_idle(self) -> None:
        def boom(text, cancel_event=None, confirmed=False, speech_confidence=None):  # noqa: ARG002
            raise RuntimeError("brain exploded")

        owner, bridge, brain, tm, cm = _make_owner(brain_process=boom)
        response = owner._run_command("open chrome")

        self.assertIsNone(response)
        self.assertEqual(tm.last_task.status, TaskStatus.FAILED)
        self.assertTrue(tm.last_task.cancel_event.is_set())
        # Continuous-conversation contract (FIX 2): _run_command never
        # forces idle mid-conversation — the caller transitions to ACTIVE
        # / LISTENING next.  The command must still end in a DEFINED
        # state (THINKING published), never stuck or silent.
        bridge.set_core_state.assert_any_call("thinking")
        self.assertEqual(cm.state, ConversationState.THINKING)
        self.assertIsNone(tm.active_task)

    def test_timeout_finalizes_failed_with_reason(self) -> None:
        def timed_out(text, cancel_event=None, confirmed=False, speech_confidence=None):  # noqa: ARG002
            return Response(
                success=False,
                message="The operation timed out after 20 seconds.",
                task_result=_PlaceholderResult("TIMEOUT"),
            )

        owner, bridge, brain, tm, cm = _make_owner(brain_process=timed_out)
        response = owner._run_command("open chrome")

        self.assertIsNotNone(response)
        self.assertEqual(tm.last_task.status, TaskStatus.FAILED)
        self.assertEqual(tm.last_task.reason, "timeout")
        self.assertTrue(tm.last_task.cancel_event.is_set())

    def test_success_finalizes_success(self) -> None:
        def ok(text, cancel_event=None, confirmed=False, speech_confidence=None):  # noqa: ARG002
            return Response(success=True, message="Done.", task_result=TaskResult.SUCCESS)

        owner, bridge, brain, tm, cm = _make_owner(brain_process=ok)
        response = owner._run_command("open chrome")

        self.assertEqual(tm.last_task.status, TaskStatus.SUCCESS)
        self.assertFalse(tm.last_task.cancel_event.is_set())
        # Continuous-conversation contract (FIX 2): see above — the turn
        # ends in defined THINKING state; the loop transitions to ACTIVE
        # and re-arms LISTENING next.
        bridge.set_core_state.assert_any_call("thinking")
        self.assertEqual(cm.state, ConversationState.THINKING)

    def test_no_response_finalizes_failed(self) -> None:
        owner, *_ = _make_owner()
        task = owner._task_manager.create_task("open chrome")
        owner._finalize_task(task, None)
        self.assertEqual(task.status, TaskStatus.FAILED)
        self.assertEqual(task.reason, "no_response")

    def test_cancelled_response_finalizes_success(self) -> None:
        owner, *_ = _make_owner()
        task = owner._task_manager.create_task("open chrome")
        response = Response(
            success=False,
            message="Cancelled.",
            task_result=TaskResult.CANCELLED,
        )
        owner._finalize_task(task, response)
        self.assertEqual(task.status, TaskStatus.SUCCESS)

    def test_internal_error_finalizes_failed(self) -> None:
        owner, *_ = _make_owner()
        task = owner._task_manager.create_task("open chrome")
        response = Response(
            success=False,
            message="An internal error occurred.",
            task_result=TaskResult.INTERNAL_ERROR,
        )
        owner._finalize_task(task, response)
        self.assertEqual(task.status, TaskStatus.FAILED)
        self.assertEqual(task.reason, "internal_error")


class TestCancelCleanState(unittest.TestCase):
    def test_cancel_active_clears_slot_and_runs_cleanup(self) -> None:
        tm = TaskManager()
        task = tm.create_task("open chrome")
        probe = MagicMock()
        tm.register_cleanup(task, probe)

        self.assertTrue(tm.cancel_active("new command"))
        self.assertIsNone(tm.active_task)
        self.assertIsNone(tm.current_task)
        probe.assert_called_once()
        self.assertTrue(task.cancel_event.is_set())

    def test_cancel_active_with_no_task_is_noop(self) -> None:
        tm = TaskManager()
        self.assertFalse(tm.cancel_active("nothing to cancel"))


class TestConversationBackToIdle(unittest.TestCase):
    def test_state_machine_can_always_reach_idle(self) -> None:
        for enter in ("wake", "thinking", "speaking", "active"):
            cm = ConversationManager()
            if enter == "wake":
                cm.on_wake_word()
            elif enter == "thinking":
                cm.on_command_received()
            elif enter == "speaking":
                cm.on_speaking()
            else:
                cm.enter_active_conversation()
            cm.return_to_idle("recovery")
            self.assertEqual(cm.state.value, "IDLE")

    def test_run_command_ends_in_conversation_idle_capability(self) -> None:
        owner, bridge, brain, tm, cm = _make_owner(
            brain_process=lambda text, cancel_event=None, confirmed=False: Response(  # noqa: ARG002
                success=True, message="Done.", task_result=TaskResult.SUCCESS,
            )
        )
        owner._run_command("open chrome")
        cm.enter_active_conversation("after")
        cm.return_to_idle("recovery")
        self.assertEqual(cm.state.value, "IDLE")


class TestSubtitleStateConsistency(unittest.TestCase):
    def test_stale_listening_label_does_not_overwrite_thinking_state(self) -> None:
        from ui.bridge import Bridge

        bridge = Bridge()
        bridge.set_core_state("thinking")
        bridge.show_subtitle("Listening...")

        self.assertEqual(bridge.coreState, "thinking")
        self.assertEqual(bridge._subtitle, "Thinking...")

    def test_stale_thinking_label_does_not_overwrite_listening_state(self) -> None:
        from ui.bridge import Bridge

        bridge = Bridge()
        bridge.set_core_state("listening")
        bridge.show_subtitle("Thinking...")

        self.assertEqual(bridge.coreState, "listening")
        self.assertEqual(bridge._subtitle, "Listening...")


if __name__ == "__main__":
    unittest.main()