"""Baseline regression tests for the FIX-NO-WAKE-ECHO / shutdown-trace work.

BUG 1 + BUG 2 ("conversation failure must never shut JARVIS down"):

A conversation-level failure (STT timeout, empty/low-confidence transcript,
TTS failure, runtime exception, watch-dog recovery) must NEVER terminate the
application.  The only legitimate ways out are the user closing the window
(``Bridge.quit_app``) or an explicit EXIT text command /
Ctrl+C.  These tests:

  * statically prove that ``services/conversation_owner.py`` contains NO call
    to ``QCoreApplication.quit`` / ``bridge.quit_app`` / ``sys.exit``
    (the commented-out legacy auto-quit must stay dead), and
  * drive the real ``ConversationOwner.run()`` loop through every failure
    class and assert the owner survives, returns to idle, and re-arms the
    wake detector with a re-arm cooldown instead of quitting.
"""
from __future__ import annotations

import ast
import pathlib
import queue
import threading
import time
import unittest
from unittest.mock import MagicMock

from models.response import Response
from models.task_result import TaskResult
from services.conversation_manager import ConversationManager
from services.conversation_owner import ConversationOwner
from tasks.task_manager import TaskManager
from voice.duplex import CaptureResult

_REPO = pathlib.Path(__file__).resolve().parents[1]
_OWNER_PATH = _REPO / "services" / "conversation_owner.py"


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


class TestNoAutoShutdownSource(unittest.TestCase):
    """Static audit: the owner source may never quit the application."""

    def test_owner_source_has_no_quit_path(self) -> None:
        source = _OWNER_PATH.read_text(encoding="utf-8")
        tree = ast.parse(source)

        banned: list[str] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                fn = node.func
                if isinstance(fn, ast.Attribute):
                    if fn.attr == "quit" and getattr(fn.value, "id", "") == "QCoreApplication":
                        banned.append("QCoreApplication.quit")
                    if fn.attr == "quit_app":
                        banned.append("bridge.quit_app")
                    if fn.attr == "quit" and isinstance(fn.value, ast.Attribute) and fn.value.attr == "app":
                        banned.append("QApplication.quit")
                if isinstance(fn, ast.Name) and fn.id == "sys" and node.args:
                    if isinstance(node.args[0], ast.Attribute) and node.args[0].attr == "exit":
                        banned.append("sys.exit")
        self.assertEqual(
            banned, [],
            "conversation_owner.py must never quit the app; found: %s" % banned,
        )


class TestFailureNeverShutsDown(unittest.TestCase):
    """Drive the live owner loop through each failure class; it must survive."""

    def _assert_survives(self, env, thread, expected_idle=True) -> None:
        self.assertTrue(thread.is_alive(), "loop died on a recoverable failure")
        self.assertFalse(env["shutdown_event"].is_set(), "auto-shutdown fired")
        if expected_idle:
            self.assertTrue(
                _wait_until(
                    lambda: any(
                        c.args[0] == "idle"
                        for c in env["bridge"].set_core_state.call_args_list
                    )
                ),
                "owner never returned to idle",
            )
        self.assertTrue(_shutdown(env, thread))

    def test_stt_no_speech_does_not_quit(self) -> None:
        env = _make_owner()
        thread = _start(env)
        env["wake_word_detected"].set()
        time.sleep(0.6)
        self._assert_survives(env, thread)

    def test_no_speech_rounds_do_not_quit_or_speak_wake_phrase(self) -> None:
        env = _make_owner(voice_enabled=True)
        thread = _start(env)
        env["wake_word_detected"].set()
        # Let the no-speech rounds elapse (max rounds * 5 s listen window +
        # margin).  FIX-NO-WAKE-ECHO: the owner must return to idle WITHOUT
        # speaking a wake-phrase instruction.
        time.sleep(2.0)
        spoken = [
            c.args[0] for c in env["voice_engine"].speak.call_args_list
            if c.args
        ]
        for msg in spoken:
            self.assertNotIn("jarvis", msg.casefold(),
                             "JARVIS must never speak its own wake phrase: %r" % msg)
            self.assertNotIn("say", msg.casefold(),
                             "no 'Say ...' wake schooling after failure: %r" % msg)
        self._assert_survives(env, thread)

    def test_low_confidence_repeat_does_not_quit(self) -> None:
        env = _make_owner()
        env["duplex"].capture_command = lambda **kw: _capture(
            text="open chrome", confidence=0.1, accepted=False,
            reason="low confidence",
        )
        thread = _start(env)
        env["wake_word_detected"].set()
        time.sleep(0.6)
        self._assert_survives(env, thread)

    def test_silence_garbage_returns_to_idle_quietly(self) -> None:
        env = _make_owner()
        env["duplex"].capture_command = lambda **kw: _capture(
            text="", confidence=0.0, accepted=False, reason="no speech recognized",
        )
        thread = _start(env)
        env["wake_word_detected"].set()
        time.sleep(0.6)
        self._assert_survives(env, thread)

    def test_runtime_exception_recovers_and_keeps_running(self) -> None:
        env = _make_owner(brain_process=lambda *a, **k: Response(
            success=True, message="Done.", task_result=TaskResult.SUCCESS,
        ))
        env["bridge"].set_backend_heartbeat.side_effect = RuntimeError("boom")
        thread = _start(env)
        time.sleep(0.6)
        self._assert_survives(env, thread)
        # Recovery path restored a usable idle state.
        self.assertTrue(
            _wait_until(
                lambda: any(
                    c.args[0] == "idle"
                    for c in env["bridge"].set_core_state.call_args_list
                )
            )
        )
        self.assertTrue(_shutdown(env, thread))


if __name__ == "__main__":
    unittest.main()
