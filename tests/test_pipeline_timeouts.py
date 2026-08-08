"""
tests/test_pipeline_timeouts.py

Regression tests for the "stuck pipeline" bug:

  1. Brain._run_with_timeout() must ALWAYS return a Response — TIMEOUT /
     INTERNAL_ERROR / CANCELLED — never None or an exception.
  2. The conversation state machine must never be stuck in a transient
     state and must always be able to return to IDLE.

(The legacy Google STT / VoiceConversationPipeline tests were removed in
FIX-002 — the active speech path is the streaming Vosk transcriber, tested
in tests/test_streaming_stt.py.)

No microphone hardware, network, or real TTS is used: everything is faked.
"""

from __future__ import annotations

import threading
import time
import unittest

from brain.brain import Brain
from models.response import Response
from services.conversation_manager import ConversationManager


class TestBrainAlwaysReturnsResponse(unittest.TestCase):
    def _hang(self, stop: threading.Event) -> Response:
        """Block until *stop* is set — simulates a hung pipeline step."""
        stop.wait(30.0)
        return Response(success=False, message="hang released")

    def test_hanging_pipeline_returns_timeout_response(self) -> None:
        brain = Brain()
        stop = threading.Event()
        started = time.monotonic()
        response = brain._run_with_timeout(lambda: self._hang(stop), timeout=0.3)
        elapsed = time.monotonic() - started
        stop.set()  # release the worker so it can exit cleanly

        self.assertIsInstance(response, Response)
        self.assertFalse(response.success)
        self.assertEqual(response.task_result.value, "TIMEOUT")
        self.assertLess(elapsed, 5.0)

    def test_never_returns_none(self) -> None:
        """Even a function returning None must be converted to a Response."""
        brain = Brain()
        response = brain._run_with_timeout(lambda: None, timeout=1.0)
        self.assertIsInstance(response, Response)
        self.assertFalse(response.success)

    def test_exception_returns_error_response(self) -> None:
        def boom():
            raise RuntimeError("boom")

        brain = Brain()
        response = brain._run_with_timeout(boom, timeout=1.0)
        self.assertIsInstance(response, Response)
        self.assertFalse(response.success)
        self.assertEqual(response.task_result.value, "INTERNAL_ERROR")

    def test_cancel_current_does_not_deadlock(self) -> None:
        """cancel_current() must return immediately and the operation must
        resolve to a Response (not hang)."""
        brain = Brain()
        stop = threading.Event()
        result: list[Response | None] = []

        def run_and_capture():
            result.append(brain._run_with_timeout(lambda: self._hang(stop), timeout=1.0))

        worker = threading.Thread(target=run_and_capture, daemon=True)
        worker.start()
        time.sleep(0.1)

        started = time.monotonic()
        brain.cancel_current()  # must not block / deadlock
        cancel_elapsed = time.monotonic() - started
        worker.join(timeout=3.0)
        stop.set()  # release any still-blocked pool worker

        self.assertLess(cancel_elapsed, 1.0, "cancel_current() must return promptly")
        self.assertFalse(worker.is_alive(), "worker must exit after cancel")
        self.assertEqual(len(result), 1)
        self.assertIsInstance(result[0], Response)


class TestConversationNeverStuck(unittest.TestCase):
    """Every transient state must be able to return to IDLE."""

    def test_all_transient_states_recover_to_idle(self) -> None:
        cm = ConversationManager()
        for enter in (
            cm.on_wake_word,
            cm.on_command_received,
            cm.on_speaking,
            cm.on_executing,
        ):
            cm = ConversationManager()
            enter()
            self.assertNotEqual(cm.state.value, "IDLE")
            cm.return_to_idle("recovery")
            self.assertEqual(cm.state.value, "IDLE")

    def test_timeout_recovers_to_idle(self) -> None:
        cm = ConversationManager()
        cm.enter_active_conversation("test")
        cm.on_timeout()
        self.assertEqual(cm.state.value, "IDLE")

    def test_confirmation_pending_recovers_to_idle(self) -> None:
        cm = ConversationManager()
        cm.request_confirmation("close_app", {"app_name": "chrome"}, "close chrome")
        self.assertEqual(cm.state.value, "WAITING_CONFIRMATION")
        cm.return_to_idle("confirmation resolved")
        self.assertEqual(cm.state.value, "IDLE")
        self.assertFalse(cm.has_pending_confirmation)


if __name__ == "__main__":
    unittest.main()
