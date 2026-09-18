"""FIX-VOICE-RUNTIME-001: regression tests proving JARVIS never terminates
itself on a recoverable runtime error.

The conversation-owner main loop must survive STT timeouts, empty/low-
confidence transcripts, LLM exceptions, executor failures, TTS failures and
arbitrary exceptions escaping the loop body — only an explicit shutdown
request (EXIT command / shutdown flag) may end the runtime.

These tests drive a real ``ConversationOwner.run()`` loop on a background
thread with mocked hardware/brain dependencies so no GUI or microphone is
needed.
"""
from __future__ import annotations

import queue
import threading
import time
import unittest
from unittest.mock import MagicMock
from unittest.mock import patch

from models.response import Response
from models.task_result import TaskResult
from services.conversation_manager import ConversationManager, ConversationState
from services.conversation_owner import ConversationOwner
from tasks.task_manager import TaskManager, TaskStatus
from voice.duplex import CaptureResult


def _capture(text="", confidence=0.0, accepted=False, reason="no_speech"):
    return CaptureResult(
        text=text,
        confidence=confidence,
        accepted=accepted,
        reason=reason,
    )


def _make_owner(*, brain_process=None, voice_enabled=False):
    bridge = MagicMock()
    brain = MagicMock()
    if brain_process is not None:
        brain.process = MagicMock(side_effect=brain_process)
    tm = TaskManager()
    cm = ConversationManager()
    response_manager = MagicMock()
    response_manager._voice_enabled = voice_enabled
    response_manager.console_text.return_value = "subtitle"
    response_manager.voice_text.return_value = "voiced subtitle"
    voice_engine = MagicMock()
    voice_engine.is_speaking = False
    voice_engine.queue_size = 0
    voice_engine.is_busy = False
    duplex = MagicMock()
    duplex.capture_command = lambda **kw: _capture(reason="no_speech")
    service_manager = MagicMock()
    service_manager.initialize_all.return_value = {}
    service_manager.start_all.return_value = {}
    service_manager.shutdown_all.return_value = {}
    shutdown_in_progress = threading.Event()
    shutdown_event = threading.Event()
    command_queue = queue.Queue()
    wake_word_detected = threading.Event()
    owner = ConversationOwner(
        conversation_manager=cm,
        bridge=bridge,
        brain=brain,
        task_manager=tm,
        response_manager=response_manager,
        voice_engine=voice_engine,
        wake_word_service=MagicMock(),
        microphone_stream=MagicMock(),
        duplex_session=duplex,
        command_queue=command_queue,
        wake_word_detected=wake_word_detected,
        watchdog_manager=MagicMock(),
        service_manager=service_manager,
        shutdown_in_progress=shutdown_in_progress,
        shutdown_event=shutdown_event,
    )
    return {
        "owner": owner,
        "bridge": bridge,
        "brain": brain,
        "tm": tm,
        "cm": cm,
        "duplex": duplex,
        "voice_engine": voice_engine,
        "q": command_queue,
        "wake_word_detected": wake_word_detected,
        "shutdown_in_progress": shutdown_in_progress,
        "shutdown_event": shutdown_event,
    }


def _start(env):
    thread = threading.Thread(target=env["owner"].run, daemon=True)
    thread.start()
    return thread


def _wait_until(cond, timeout=5.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if cond():
            return True
        time.sleep(0.02)
    return cond()


def _shutdown(env, thread):
    env["shutdown_in_progress"].set()
    env["q"].put("exit")
    thread.join(timeout=5.0)
    return not thread.is_alive()


class TestRuntimePersistence(unittest.TestCase):
    def test_stt_timeout_does_not_terminate(self) -> None:
        """No speech / STT timeout must return to a ready state, not exit."""
        env = _make_owner()
        thread = _start(env)
        env["wake_word_detected"].set()
        self.assertTrue(_wait_until(lambda: True))  # let the loop run
        time.sleep(0.5)
        self.assertTrue(thread.is_alive(), "loop died after STT timeout")
        self.assertFalse(env["shutdown_event"].is_set())
        # It returned to the ready/idle state rather than exiting.
        self.assertTrue(
            _wait_until(
                lambda: any(
                    c.args[0] == "idle" for c in env["bridge"].set_core_state.call_args_list
                )
            ),
            "owner never returned to idle after STT timeout",
        )
        self.assertTrue(_shutdown(env, thread))

    def test_empty_transcript_does_not_terminate(self) -> None:
        env = _make_owner()
        env["duplex"].capture_command = lambda **kw: _capture(
            text="", confidence=0.0, accepted=True, reason=""
        )
        thread = _start(env)
        env["wake_word_detected"].set()
        time.sleep(0.6)
        self.assertTrue(thread.is_alive(), "loop died after empty transcript")
        self.assertFalse(env["shutdown_event"].is_set())
        self.assertTrue(_shutdown(env, thread))

    def test_loop_body_exception_recovers_and_keeps_running(self) -> None:
        """The key regression: any exception escaping the loop body must be
        recovered inside the loop — it must never reach the finally block
        that quits the application."""
        env = _make_owner(brain_process=lambda *a, **k: Response(
            success=True, message="Done.", task_result=TaskResult.SUCCESS,
        ))
        env["bridge"].set_backend_heartbeat.side_effect = RuntimeError("heartbeat boom")
        thread = _start(env)
        time.sleep(0.5)
        self.assertTrue(thread.is_alive(), "loop died on loop-body exception")
        self.assertFalse(env["shutdown_event"].is_set())
        # Recovery path restored a usable (idle) state.
        self.assertTrue(
            _wait_until(
                lambda: any(
                    c.args[0] == "idle" for c in env["bridge"].set_core_state.call_args_list
                )
            ),
            "no idle recovery after loop-body exception",
        )
        # Rigging fails once, then commands still work.
        env["bridge"].set_backend_heartbeat.side_effect = None
        env["q"].put("open chrome")
        self.assertTrue(
            _wait_until(
                lambda: env["tm"].last_task is not None
                and env["tm"].last_task.is_terminal
            ),
            "command never finalized after recovery",
        )
        self.assertEqual(env["tm"].last_task.status, TaskStatus.SUCCESS)
        self.assertTrue(_shutdown(env, thread))

    def test_llm_exception_does_not_terminate(self) -> None:
        def boom(text, cancel_event=None, **kw):  # noqa: ARG002
            raise RuntimeError("LLM exploded")

        env = _make_owner(brain_process=boom)
        thread = _start(env)
        env["q"].put("open chrome")
        self.assertTrue(
            _wait_until(
                lambda: env["tm"].last_task is not None
                and env["tm"].last_task.is_terminal
            ),
            "command never finalized",
        )
        self.assertTrue(thread.is_alive(), "loop died after LLM exception")
        self.assertFalse(env["shutdown_event"].is_set())
        self.assertEqual(env["tm"].last_task.status, TaskStatus.FAILED)
        self.assertTrue(_shutdown(env, thread))

    def test_executor_failure_does_not_terminate(self) -> None:
        env = _make_owner(brain_process=lambda *a, **k: Response(
            success=False,
            message="Sorry sir, I couldn't open Chrome.",
            task_result=TaskResult.FAILED,
        ))
        thread = _start(env)
        env["q"].put("open chrome")
        self.assertTrue(
            _wait_until(
                lambda: env["tm"].last_task is not None
                and env["tm"].last_task.is_terminal
            ),
            "command never finalized",
        )
        self.assertTrue(thread.is_alive(), "loop died after executor failure")
        self.assertFalse(env["shutdown_event"].is_set())
        self.assertEqual(env["tm"].last_task.status, TaskStatus.FAILED)
        self.assertTrue(_shutdown(env, thread))

    def test_tts_failure_does_not_terminate(self) -> None:
        """A raise inside VoiceEngine.speak must be swallowed by
        _speak_with_retry and the runtime must keep listening."""
        env = _make_owner(
            brain_process=lambda *a, **k: Response(
                success=True, message="Chrome is open.", task_result=TaskResult.SUCCESS,
            ),
            voice_enabled=True,
        )
        env["voice_engine"].speak.side_effect = RuntimeError("TTs provider down")

        thread = _start(env)
        env["q"].put("open chrome")
        self.assertTrue(
            _wait_until(
                lambda: env["tm"].last_task is not None
                and env["tm"].last_task.is_terminal
            ),
            "command never finalized",
        )
        self.assertTrue(thread.is_alive(), "loop died after TTS failure")
        self.assertFalse(env["shutdown_event"].is_set())
        self.assertEqual(env["tm"].last_task.status, TaskStatus.SUCCESS)
        # It continued on to the engage/follow-up state.
        self.assertTrue(_shutdown(env, thread))

    def test_success_returns_to_ready_listening_state(self) -> None:
        env = _make_owner(brain_process=lambda *a, **k: Response(
            success=True, message="Chrome is open.", task_result=TaskResult.SUCCESS,
        ))
        thread = _start(env)
        env["q"].put("open chrome")
        self.assertTrue(
            _wait_until(
                lambda: env["tm"].last_task is not None
                and env["tm"].last_task.is_terminal
            ),
            "command never finalized",
        )
        self.assertEqual(env["tm"].last_task.status, TaskStatus.SUCCESS)
        self.assertTrue(thread.is_alive())
        # A second command still processes → the loop stayed engaged.
        env["q"].put("open calculator")
        self.assertTrue(
            _wait_until(lambda: env["brain"].process.call_count >= 2),
            "second command never processed",
        )
        self.assertTrue(thread.is_alive())
        self.assertTrue(_shutdown(env, thread))

    def test_alive_after_multiple_failed_commands(self) -> None:
        def boom(text, cancel_event=None, **kw):  # noqa: ARG002
            raise RuntimeError("repeat failure")

        env = _make_owner(brain_process=boom)
        thread = _start(env)
        for _ in range(5):
            env["q"].put("open chrome")
        self.assertTrue(
            _wait_until(lambda: env["brain"].process.call_count >= 5),
            "expected 5 command attempts",
        )
        # After the failures are recovered, no task may remain active and the
        # loop must still be processing the queue.
        self.assertTrue(
            _wait_until(lambda: env["tm"].active_task is None),
            "a task was left dangling after failures",
        )
        self.assertTrue(thread.is_alive(), "loop died after 5 failed commands")
        self.assertFalse(env["shutdown_event"].is_set())
        self.assertTrue(_shutdown(env, thread))

    def test_explicit_shutdown_still_works(self) -> None:
        env = _make_owner()
        thread = _start(env)
        time.sleep(0.3)
        self.assertTrue(thread.is_alive())
        self.assertTrue(_shutdown(env, thread))
        self.assertTrue(env["shutdown_event"].is_set())


class TestCommandPathReachesExecutor(unittest.TestCase):
    """STEP 5: a recognized command travels from STT transcript to executor.

    The conversation owner routes the transcript to brain.process (the
    intent→executor stage); we verify the accepted transcript is forwarded
    and that a low-confidence / empty transcript is NOT forwarded.
    """

    def test_accepted_text_command_reaches_executor(self) -> None:
        seen = []

        def brain_process(text, cancel_event=None, **kw):  # noqa: ARG002
            seen.append(text)
            return Response(success=True, message="Done.", task_result=TaskResult.SUCCESS)

        env = _make_owner(brain_process=brain_process)
        thread = _start(env)
        env["q"].put("open chrome")
        self.assertTrue(_wait_until(lambda: len(seen) >= 1))
        self.assertEqual(seen, ["open chrome"])
        self.assertTrue(_shutdown(env, thread))

    def test_accepted_voice_command_reaches_executor(self) -> None:
        seen = []

        def brain_process(text, cancel_event=None, **kw):  # noqa: ARG002
            seen.append(text)
            return Response(success=True, message="Done.", task_result=TaskResult.SUCCESS)

        env = _make_owner(brain_process=brain_process)
        env["duplex"].capture_command = lambda **kw: _capture(
            text="open calculator", confidence=0.92, accepted=True, reason="",
        )
        thread = _start(env)
        env["wake_word_detected"].set()
        self.assertTrue(_wait_until(lambda: len(seen) >= 1))
        self.assertEqual(seen, ["open calculator"])
        self.assertTrue(_shutdown(env, thread))

    def test_low_confidence_voice_never_reaches_executor(self) -> None:
        seen = []

        def brain_process(text, cancel_event=None, **kw):  # noqa: ARG002
            seen.append(text)
            return Response(success=True, message="Done.", task_result=TaskResult.SUCCESS)

        env = _make_owner(brain_process=brain_process)
        env["duplex"].capture_command = lambda **kw: _capture(
            text="open chrome", confidence=0.1, accepted=False, reason="low confidence",
        )
        thread = _start(env)
        env["wake_word_detected"].set()
        time.sleep(0.8)
        self.assertEqual(seen, [], "low-confidence transcript must not execute")
        self.assertTrue(thread.is_alive())
        self.assertTrue(_shutdown(env, thread))


if __name__ == "__main__":
    unittest.main()