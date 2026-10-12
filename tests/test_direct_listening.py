"""Regression tests for VOICE-PIPELINE-004: direct listening, no wake word.

JARVIS now enters the listen/capture loop directly whenever it is IDLE, so a
command can be spoken at any time without first saying "JARVIS".  These tests
drive the real ``ConversationOwner.run()`` loop WITHOUT ever setting the
wake-word event and assert:

  1. the owner still captures audio and enters the "listening" state,
  2. silent background never produces spoken filler (TTS stays quiet),
  3. low-confidence speech is never executed and never spoken as a repeat nag,
  4. an accepted spoken command is still dispatched to the brain.
"""
from __future__ import annotations

import pathlib
import queue
import threading
import time
import unittest
from unittest.mock import MagicMock

from fake_bridge import FakeBridge
from models.response import Response
from models.task_result import TaskResult
from services.conversation_manager import ConversationManager, ConversationState
from services.conversation_owner import ConversationOwner
from tasks.task_manager import TaskManager
from voice.duplex import CaptureResult

_BANNED_SPOKEN = (
    "i'm still listening",
    "i am still listening",
    "sorry sir",
    "could you repeat",
    "please try again",
    "i didn't catch that",
    "listen for the wake",
    "say jarvis",
)


def _capture(text="", confidence=0.0, accepted=False, reason="no_speech"):
    return CaptureResult(
        text=text,
        confidence=confidence,
        accepted=accepted,
        reason=reason,
    )


def _make_owner(*, brain_process=None, voice_enabled=False, capture=None,
                wake_word_enabled=None):
    # Bridge-faithful double: the owner publishes through emit_* (like the
    # real ui.bridge.Bridge), so a bare MagicMock would record no state.
    bridge = FakeBridge()
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
    if capture is None:
        capture = lambda **kw: _capture(reason="no_speech")
    duplex.capture_command = MagicMock(side_effect=capture)
    service_manager = MagicMock()
    service_manager.initialize_all.return_value = {}
    service_manager.start_all.return_value = {}
    service_manager.shutdown_all.return_value = {}
    shutdown_in_progress = threading.Event()
    shutdown_event = threading.Event()
    command_queue = queue.Queue()
    wake_word_detected = threading.Event()
    wake_word_service = MagicMock()
    owner = ConversationOwner(
        conversation_manager=cm,
        bridge=bridge,
        brain=brain,
        task_manager=tm,
        response_manager=response_manager,
        voice_engine=voice_engine,
        wake_word_service=wake_word_service,
        microphone_stream=MagicMock(),
        duplex_session=duplex,
        command_queue=command_queue,
        wake_word_detected=wake_word_detected,
        watchdog_manager=MagicMock(),
        service_manager=service_manager,
        shutdown_in_progress=shutdown_in_progress,
        shutdown_event=shutdown_event,
        wake_word_enabled=wake_word_enabled,
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
        "wake_word_service": wake_word_service,
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


def _core_states(env):
    return list(env["bridge"].core_states)


def _spoken_messages(env):
    return [
        c.args[0] for c in env["voice_engine"].speak.call_args_list if c.args
    ]


class TestDirectListening(unittest.TestCase):

    def test_captures_audio_without_any_wake_event(self) -> None:
        """Direct listening: the owner captures even though wake never fires."""
        env = _make_owner()
        thread = _start(env)
        try:
            self.assertTrue(
                _wait_until(lambda: env["duplex"].capture_command.call_count >= 1),
                "owner never entered the direct listen/capture loop",
            )
            self.assertTrue(
                _wait_until(lambda: "listening" in _core_states(env)),
                "owner never entered the 'listening' core state",
            )
            self.assertFalse(
                env["wake_word_detected"].is_set(),
                "test harness wake event must stay unset",
            )
            self.assertTrue(thread.is_alive())
        finally:
            self.assertTrue(_shutdown(env, thread))

    def test_silent_background_never_speaks_filler(self) -> None:
        """No speech: JARVIS stays quiet (no 'I'm still listening.' etc.)."""
        env = _make_owner(voice_enabled=True)
        thread = _start(env)
        try:
            self.assertTrue(
                _wait_until(lambda: env["duplex"].capture_command.call_count >= 3),
                "direct listen loop is not cycling",
            )
            time.sleep(0.6)
            for msg in _spoken_messages(env):
                low = msg.casefold()
                for banned in _BANNED_SPOKEN:
                    self.assertNotIn(
                        banned, low,
                        "silent background must not speak %r: %r" % (banned, msg),
                    )
            self.assertTrue(thread.is_alive())
        finally:
            self.assertTrue(_shutdown(env, thread))

    def test_low_confidence_never_executed_or_spoken(self) -> None:
        """Low confidence: no execution, no spoken repeat nag, back to idle."""
        env = _make_owner(
            voice_enabled=True,
            capture=lambda **kw: _capture(
                text="open chrome", confidence=0.1, accepted=False,
                reason="low confidence",
            ),
        )
        thread = _start(env)
        try:
            self.assertTrue(
                _wait_until(lambda: env["duplex"].capture_command.call_count >= 3),
                "direct listen loop is not cycling",
            )
            self.assertEqual(
                env["brain"].process.call_count, 0,
                "low-confidence speech must never reach the brain",
            )
            for msg in _spoken_messages(env):
                low = msg.casefold()
                for banned in _BANNED_SPOKEN:
                    self.assertNotIn(
                        banned, low,
                        "low-confidence path must not speak %r: %r" % (banned, msg),
                    )
            self.assertTrue(
                _wait_until(lambda: env["cm"].state == ConversationState.LISTENING),
                "owner left the stable listening state",
            )
            self.assertTrue(thread.is_alive())
        finally:
            self.assertTrue(_shutdown(env, thread))

    def test_direct_no_speech_stays_in_listening_state(self) -> None:
        """No speech in direct mode must not bounce IDLE -> LISTENING."""
        env = _make_owner(wake_word_enabled=False)
        thread = _start(env)
        try:
            self.assertTrue(
                _wait_until(lambda: env["duplex"].capture_command.call_count >= 3),
                "direct listen loop is not cycling",
            )
            self.assertEqual(env["cm"].state, ConversationState.LISTENING)
            self.assertTrue(thread.is_alive())
        finally:
            self.assertTrue(_shutdown(env, thread))

    def test_accepted_speech_still_dispatches_to_brain(self) -> None:
        """Direct listening still executes a clearly-spoken command once."""
        state = {"captures": 0}

        def capture(**kw):
            state["captures"] += 1
            if state["captures"] == 1:
                return _capture(
                    text="open chrome", confidence=0.95, accepted=True, reason="",
                )
            return _capture(reason="no_speech")

        env = _make_owner(
            voice_enabled=False,
            capture=capture,
            brain_process=lambda *a, **k: Response(
                success=True, message="Done.", task_result=TaskResult.SUCCESS,
            ),
        )
        thread = _start(env)
        try:
            self.assertTrue(
                _wait_until(lambda: env["brain"].process.call_count >= 1),
                "accepted direct-listening command never reached the brain",
            )
            called = [
                c.args[0] for c in env["brain"].process.call_args_list
            ]
            self.assertEqual(called, ["open chrome"])
            self.assertEqual(
                env["brain"].process.call_count, 1,
                "command must be dispatched exactly once",
            )
            self.assertTrue(thread.is_alive())
        finally:
            self.assertTrue(_shutdown(env, thread))

    # ── WAKE_WORD_ENABLED=false (VOICE-PIPELINE-004) ──────────────────

    def test_direct_listening_never_enters_wake_detected(self) -> None:
        """With WAKE_WORD_ENABLED=false no WAKE_DETECTED/'wake word heard' occurs."""
        env = _make_owner(wake_word_enabled=False)
        # Spy: if the owner ever called the wake callback we'd catch it here.
        wake_calls: list[bool] = []
        env["cm"].on_wake_word = lambda: wake_calls.append(True)
        thread = _start(env)
        try:
            self.assertTrue(
                _wait_until(
                    lambda: env["cm"].state == ConversationState.LISTENING
                ),
                "owner must record the true LISTENING state in direct mode",
            )
            self.assertTrue(
                _wait_until(lambda: env["duplex"].capture_command.call_count >= 2),
                "direct listen loop is not cycling",
            )
            self.assertEqual(
                wake_calls, [],
                "no wake callback may fire when WAKE_WORD_ENABLED=false",
            )
            self.assertNotEqual(
                env["cm"].state, ConversationState.WAKE_DETECTED
            )
            self.assertFalse(
                env["wake_word_detected"].is_set(),
                "no WAKE_DETECTED event may be produced",
            )
            self.assertTrue(thread.is_alive())
        finally:
            self.assertTrue(_shutdown(env, thread))

    def test_wake_service_not_required_to_begin_command(self) -> None:
        """A command runs with no wake event and no arming of the wake service."""
        state = {"captures": 0}

        def capture(**kw):
            state["captures"] += 1
            if state["captures"] == 1:
                return _capture(
                    text="open chrome", confidence=0.96, accepted=True, reason="",
                )
            return _capture(reason="no_speech")

        env = _make_owner(
            wake_word_enabled=False,
            capture=capture,
            brain_process=lambda *a, **k: Response(
                success=True, message="Done.", task_result=TaskResult.SUCCESS,
            ),
        )
        thread = _start(env)
        try:
            self.assertTrue(
                _wait_until(lambda: env["brain"].process.call_count >= 1),
                "command never reached the brain",
            )
            self.assertFalse(
                env["wake_word_detected"].is_set(),
                "WakeWordService must not be required to begin the command",
            )
            env["wake_word_service"].start_wake_detection.assert_not_called()
            self.assertTrue(thread.is_alive())
        finally:
            self.assertTrue(_shutdown(env, thread))

    def test_open_chrome_without_wake_word(self) -> None:
        """"Open Chrome" reaches the brain without saying "JARVIS" first."""
        state = {"captures": 0}

        def capture(**kw):
            state["captures"] += 1
            if state["captures"] == 1:
                return _capture(
                    text="open chrome", confidence=0.95, accepted=True, reason="",
                )
            return _capture(reason="no_speech")

        env = _make_owner(
            wake_word_enabled=False,
            capture=capture,
            brain_process=lambda *a, **k: Response(
                success=True, message="Done.", task_result=TaskResult.SUCCESS,
            ),
        )
        wake_calls: list[bool] = []
        env["cm"].on_wake_word = lambda: wake_calls.append(True)
        thread = _start(env)
        try:
            self.assertTrue(
                _wait_until(lambda: env["brain"].process.call_count >= 1),
                "'open chrome' never reached the brain",
            )
            self.assertEqual(
                [c.args[0] for c in env["brain"].process.call_args_list],
                ["open chrome"],
            )
            self.assertEqual(wake_calls, [], "no wake word was spoken, none heard")
            self.assertFalse(env["wake_word_detected"].is_set())
            self.assertTrue(thread.is_alive())
        finally:
            self.assertTrue(_shutdown(env, thread))

    def test_gated_mode_waits_for_wake_event(self) -> None:
        """Control: with WAKE_WORD_ENABLED=true the owner waits for the event."""
        # A capture that returns instantly would let the no-speech rounds race
        # past WAKE_DETECTED before the assertion can observe it; a real
        # capture blocks, so this stub blocks briefly too.
        def _blocking_capture(**_kwargs):
            time.sleep(0.05)
            return _capture(reason="no_speech")

        env = _make_owner(
            wake_word_enabled=True, capture=_blocking_capture,
        )
        thread = _start(env)
        try:
            time.sleep(0.4)
            self.assertEqual(
                env["duplex"].capture_command.call_count, 0,
                "wake-gated mode must NOT listen until an event fires",
            )
            env["wake_word_detected"].set()
            self.assertTrue(
                _wait_until(lambda: env["duplex"].capture_command.call_count >= 1),
                "wake-gated mode never entered the capture loop after the event",
            )
            self.assertTrue(
                _wait_until(
                    lambda: env["cm"].state == ConversationState.WAKE_DETECTED
                ),
                "a real wake event should transition honestly to WAKE_DETECTED",
            )
            self.assertTrue(thread.is_alive())
        finally:
            self.assertTrue(_shutdown(env, thread))


if __name__ == "__main__":
    unittest.main()
