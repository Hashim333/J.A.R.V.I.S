"""Regression tests for the JARVIS continuous-listening lifecycle.

Covers the P0/P1 forensic findings without requiring a microphone:

  1. Generation safety: a cancel (or VAD event) issued for a previous turn
     can never abort or complete the current turn's capture.
  2. Re-arm: consecutive captures on one DuplexVoiceSession all succeed —
     no worker/thread dies after one turn.
  3. Owner loop: 10 scripted conversational turns run back-to-back with no
     manual restart and no wake word, and listening keeps cycling after.
  4. Readiness: LISTENING is only published after the mic path is verified;
     a stolen consumer or a stale mute is self-healed.
  5. TTS lifecycle: utterance-started/finished hooks always pair, even on
     failure, so the mic-mute guard can never wedge the mic muted.

Uses the real DuplexVoiceSession / ConversationOwner / ConversationManager /
TaskManager / VoiceManager — only audio I/O, STT decoding, and TTS playback
are faked.
"""
from __future__ import annotations

import queue
import threading
import time
import unittest
from unittest.mock import MagicMock

from models.response import Response
from models.task_result import TaskResult
from services.conversation_manager import ConversationManager, ConversationState
from services.conversation_owner import ConversationOwner
from tasks.task_manager import TaskManager
from voice.duplex import CaptureResult, DuplexVoiceSession
from voice.manager import VoiceManager
from voice.streaming_stt import FinalTranscript


# ----------------------------------------------------------------------
# Fakes (same shape as tests/test_duplex.py)
# ----------------------------------------------------------------------

class PassthroughDSP:
    def process(self, chunk: bytes) -> bytes:
        return chunk

    def set_reference(self, chunk: bytes, sample_rate: int = 16000) -> None:
        pass


class FakeTranscriber:
    def __init__(self, final: FinalTranscript) -> None:
        self._final = final
        self.started = 0
        self.discarded = False
        self._finished = False

    def begin(self) -> None:
        self.started += 1
        self._finished = False

    def push(self, chunk: bytes):
        return None

    def partial_text(self) -> str:
        return ""

    def finalize(self, voiced_seconds: float | None = None) -> FinalTranscript:
        self._finished = True
        return self._final

    def discard(self) -> None:
        self.discarded = True
        self._finished = True

    def reset(self) -> None:
        pass


class FakeVAD:
    def __init__(self) -> None:
        self.reset_count = 0
        self._triggered = False

    def process_audio(self, chunk: bytes) -> None:
        pass

    def reset(self) -> None:
        self.reset_count += 1

    def set_noise_floor(self, noise_floor) -> None:
        pass

    @property
    def triggered(self) -> bool:
        return self._triggered

    @property
    def backend(self) -> str:
        return "fake"


def _make_session(final: FinalTranscript | None = None):
    transcriber = FakeTranscriber(
        final or FinalTranscript("hello jarvis", 0.9, True, duration_ms=800.0)
    )
    session = DuplexVoiceSession(
        sample_rate=16000,
        echo_canceller=PassthroughDSP(),  # type: ignore[arg-type]
        noise_suppressor=PassthroughDSP(),  # type: ignore[arg-type]
        transcriber=transcriber,  # type: ignore[arg-type]
        silence_hangover_ms=500.0,
        max_capture_timeout=30.0,
        capture_vad=FakeVAD(),  # type: ignore[arg-type]
        barge_in_vad=FakeVAD(),  # type: ignore[arg-type]
    )
    return session, transcriber


def _feed_later(session, events, delay: float = 0.05) -> None:
    def run() -> None:
        time.sleep(delay)
        for event in events:
            session._events.put(event)
            time.sleep(0.02)

    threading.Thread(target=run, daemon=True).start()


def _speech_events(voiced_seconds: float = 0.8) -> list[tuple]:
    now = time.monotonic()
    return [("speech_start", now - voiced_seconds), ("speech_end", now)]


# ----------------------------------------------------------------------
# 1. Generation safety
# ----------------------------------------------------------------------

class TestCaptureGenerations(unittest.TestCase):
    def test_stale_cancel_before_start_does_not_abort_next_capture(self) -> None:
        """A cancel issued for a finished turn must not kill the next turn.

        (Task cleanup / watchdog recovery can fire cancel_capture() after
        its turn already ended — the next capture starts a new generation
        and must ignore it instead of dropping a real utterance.)
        """
        session, _ = _make_session()
        session.cancel_capture()  # targets generation 0; nothing is capturing
        _feed_later(session, _speech_events())

        result = session.capture_command(timeout=2.0)

        self.assertTrue(result.success, f"stale cancel aborted capture: {result!r}")
        self.assertEqual(result.text, "hello jarvis")

    def test_targeted_cancel_aborts_only_its_own_turn(self) -> None:
        session, _ = _make_session()
        outcomes: list[CaptureResult] = []

        def first() -> None:
            outcomes.append(session.capture_command(timeout=5.0))

        thread = threading.Thread(target=first, daemon=True)
        thread.start()
        self.assertTrue(
            _wait_until(lambda: session.is_capture_active, timeout=3.0),
            "first capture never armed",
        )
        # Speech is underway (Phase B), then the owner cancels this turn.
        session._events.put(("speech_start", time.monotonic() - 0.8))
        time.sleep(0.1)
        session.cancel_capture()
        thread.join(timeout=5.0)

        self.assertFalse(thread.is_alive(), "cancelled capture did not exit")
        self.assertEqual(len(outcomes), 1)
        self.assertEqual(outcomes[0].reason, "cancelled")

        # The NEXT turn re-arms cleanly and captures normally.
        _feed_later(session, _speech_events())
        second = session.capture_command(timeout=2.0)
        self.assertTrue(second.success, f"next turn failed to re-arm: {second!r}")

    def test_late_vad_event_from_previous_turn_is_ignored(self) -> None:
        session, _ = _make_session()
        _feed_later(session, _speech_events())
        first = session.capture_command(timeout=2.0)
        self.assertTrue(first.success)
        stale_gen = session.capture_generation

        # A late duplicate of the previous turn's onset/end arrives during
        # the next turn (before the fresh onset) — it must not complete it.
        _feed_later(session, [
            ("speech_start", time.monotonic() - 0.8, stale_gen),
            ("speech_end", time.monotonic(), stale_gen),
            ("speech_start", time.monotonic() - 0.8),  # fresh (untagged)
            ("speech_end", time.monotonic()),
        ])
        second = session.capture_command(timeout=3.0)

        self.assertTrue(second.success, f"next turn dropped: {second!r}")
        self.assertNotEqual(session.capture_generation, stale_gen)

    def test_consecutive_captures_all_rearm(self) -> None:
        """Three back-to-back turns on one session — no worker dies."""
        session, transcriber = _make_session()
        for turn in range(3):
            _feed_later(session, _speech_events())
            result = session.capture_command(timeout=2.0)
            self.assertTrue(result.success, f"turn {turn + 1} failed: {result!r}")
        self.assertEqual(transcriber.started, 3)
        self.assertFalse(session.is_capture_active)


# ----------------------------------------------------------------------
# 2. Owner loop across many turns (no wake word, no manual restart)
# ----------------------------------------------------------------------

def _capture(text="", confidence=0.0, accepted=False, reason="no_speech"):
    return CaptureResult(
        text=text, confidence=confidence, accepted=accepted, reason=reason,
    )


def _wait_until(cond, timeout=10.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if cond():
            return True
        time.sleep(0.02)
    return cond()


class TestOwnerMultiTurnLoop(unittest.TestCase):
    def _make_owner(self, script: list[CaptureResult]):
        calls = {"n": 0}

        def capture(**kw):
            calls["n"] += 1
            if calls["n"] <= len(script):
                return script[calls["n"] - 1]
            return _capture(reason="no_speech")

        bridge = MagicMock()
        brain = MagicMock()
        brain.process = MagicMock(side_effect=lambda *a, **k: Response(
            success=True, message="Done.", task_result=TaskResult.SUCCESS,
        ))
        response_manager = MagicMock()
        response_manager._voice_enabled = False
        response_manager.console_text.return_value = "subtitle"
        voice_engine = MagicMock()
        voice_engine.is_speaking = False
        voice_engine.queue_size = 0
        voice_engine.is_busy = False
        duplex = MagicMock()
        duplex.capture_command = MagicMock(side_effect=capture)
        # Real duplex method under test elsewhere; here the mock stands in
        # for the audio path while the REAL owner/manager/task loop runs.
        duplex.process_chunk = MagicMock()
        service_manager = MagicMock()
        service_manager.initialize_all.return_value = {}
        service_manager.start_all.return_value = {}
        service_manager.shutdown_all.return_value = {}
        cm = ConversationManager()
        tm = TaskManager()
        shutdown_in_progress = threading.Event()
        command_queue: queue.Queue = queue.Queue()
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
            wake_word_detected=threading.Event(),
            watchdog_manager=MagicMock(),
            service_manager=service_manager,
            shutdown_in_progress=shutdown_in_progress,
            shutdown_event=threading.Event(),
            wake_word_enabled=False,
        )
        # Mic path reports healthy so readiness never blocks the loop.
        owner._microphone_stream.consumer_is.return_value = True
        owner._microphone_stream.is_running = True
        owner._microphone_stream.is_muted = False
        return owner, bridge, brain, cm, duplex, shutdown_in_progress, command_queue

    def test_ten_consecutive_turns_then_keeps_listening(self) -> None:
        commands = [
            "hello jarvis",
            "what is python",
            "tell me a short joke",
            "what did i just ask you",
            "open chrome",
            "close it",
            "what time is it",
            "search cats on youtube",
            "tell me another joke",
            "thank you",
        ]
        script = [
            _capture(text=c, confidence=0.95, accepted=True, reason="")
            for c in commands
        ]
        owner, bridge, brain, cm, duplex, shutdown, q = self._make_owner(script)
        thread = threading.Thread(target=owner.run, daemon=True)
        thread.start()
        try:
            self.assertTrue(
                _wait_until(lambda: brain.process.call_count >= 10, timeout=15.0),
                "owner did not complete 10 consecutive turns",
            )
            heard = [c.args[0] for c in brain.process.call_args_list[:10]]
            # The owner strips a leading/trailing wake word before dispatch
            # ("hello jarvis" -> "hello") — that is intended, not a drop.
            expected = [commands[0].replace(" jarvis", "")] + commands[1:]
            self.assertEqual(heard, expected)
            # After the 10th turn the loop must keep listening (re-arm),
            # never die or wedge in a terminal state.
            count_at_ten = duplex.capture_command.call_count
            self.assertTrue(
                _wait_until(
                    lambda: duplex.capture_command.call_count > count_at_ten + 2,
                    timeout=10.0,
                ),
                "listening did not re-arm after the 10th turn",
            )
            self.assertTrue(thread.is_alive(), "owner loop died mid-conversation")
            self.assertIn(
                cm.state,
                (
                    ConversationState.IDLE,
                    ConversationState.LISTENING,
                    ConversationState.ACTIVE_CONVERSATION,
                ),
                f"manager stuck in {cm.state}",
            )
            states = [c.args[0] for c in bridge.set_core_state.call_args_list]
            self.assertIn("listening", states)
        finally:
            shutdown.set()
            q.put("exit")
            thread.join(timeout=5.0)
            self.assertFalse(thread.is_alive(), "owner loop did not shut down")

    def test_empty_then_real_command_recovers(self) -> None:
        """Noise/empty events must not wedge the loop — the next real
        command on the very next turn is still captured."""
        script = [
            _capture(text="", confidence=0.0, accepted=False, reason="too short"),
            _capture(text="", confidence=0.0, accepted=False, reason="no speech recognized"),
            _capture(text="open chrome", confidence=0.95, accepted=True, reason=""),
        ]
        owner, bridge, brain, cm, duplex, shutdown, q = self._make_owner(script)
        thread = threading.Thread(target=owner.run, daemon=True)
        thread.start()
        try:
            self.assertTrue(
                _wait_until(lambda: brain.process.call_count >= 1, timeout=10.0),
                "real command after noise was never captured",
            )
            self.assertEqual(brain.process.call_args_list[0].args[0], "open chrome")
            self.assertTrue(thread.is_alive())
        finally:
            shutdown.set()
            q.put("exit")
            thread.join(timeout=5.0)


# ----------------------------------------------------------------------
# 3. Listening readiness gate
# ----------------------------------------------------------------------

class TestListeningReadiness(unittest.TestCase):
    def _make_owner(self):
        owner = ConversationOwner(
            conversation_manager=ConversationManager(),
            bridge=MagicMock(),
            brain=MagicMock(),
            task_manager=TaskManager(),
            response_manager=MagicMock(),
            voice_engine=MagicMock(),
            wake_word_service=MagicMock(),
            microphone_stream=MagicMock(),
            duplex_session=MagicMock(),
            command_queue=queue.Queue(),
            wake_word_detected=threading.Event(),
            watchdog_manager=MagicMock(),
            service_manager=MagicMock(),
            shutdown_in_progress=threading.Event(),
            shutdown_event=threading.Event(),
            wake_word_enabled=False,
        )
        return owner

    def test_healthy_path_reports_ready(self) -> None:
        owner = self._make_owner()
        owner._microphone_stream.consumer_is.return_value = True
        owner._microphone_stream.is_running = True
        owner._microphone_stream.is_muted = False

        self.assertTrue(owner._ensure_listening_ready())
        owner._microphone_stream.set_consumer.assert_not_called()
        owner._microphone_stream.unmute.assert_not_called()

    def test_stolen_consumer_is_restored(self) -> None:
        owner = self._make_owner()
        owner._microphone_stream.consumer_is.return_value = False
        owner._microphone_stream.is_running = True
        owner._microphone_stream.is_muted = False

        self.assertTrue(owner._ensure_listening_ready())
        owner._microphone_stream.set_consumer.assert_called_once_with(
            owner._duplex_session.process_chunk
        )

    def test_stale_mute_is_released(self) -> None:
        owner = self._make_owner()
        owner._microphone_stream.consumer_is.return_value = True
        owner._microphone_stream.is_running = True
        owner._microphone_stream.is_muted = True
        owner._microphone_stream.mute_owners = ("tts",)

        self.assertTrue(owner._ensure_listening_ready())
        owner._microphone_stream.unmute.assert_called_once_with()

    def test_dead_capture_thread_reports_not_ready(self) -> None:
        owner = self._make_owner()
        owner._microphone_stream.consumer_is.return_value = True
        owner._microphone_stream.is_running = False

        self.assertFalse(owner._ensure_listening_ready())


# ----------------------------------------------------------------------
# 4. Dead microphone: honest error, never fake LISTENING, restart retry
# ----------------------------------------------------------------------

class TestMicDeadRecovery(unittest.TestCase):
    def _make_owner(self):
        service_manager = MagicMock()
        service_manager.initialize_all.return_value = {}
        service_manager.start_all.return_value = {}
        service_manager.shutdown_all.return_value = {}
        owner = ConversationOwner(
            conversation_manager=ConversationManager(),
            bridge=MagicMock(),
            brain=MagicMock(),
            task_manager=TaskManager(),
            response_manager=MagicMock(),
            voice_engine=MagicMock(),
            wake_word_service=MagicMock(),
            microphone_stream=MagicMock(),
            duplex_session=MagicMock(),
            command_queue=queue.Queue(),
            wake_word_detected=threading.Event(),
            watchdog_manager=MagicMock(),
            service_manager=service_manager,
            shutdown_in_progress=threading.Event(),
            shutdown_event=threading.Event(),
            wake_word_enabled=False,
        )
        return owner

    def test_dead_mic_publishes_error_once_and_restarts(self) -> None:
        owner = self._make_owner()
        mic = owner._microphone_stream
        mic.is_running = False

        self.assertFalse(owner._ensure_listening_ready())
        owner._handle_listening_not_ready(owner._bridge)
        owner._handle_listening_not_ready(owner._bridge)  # within retry gate

        states = [c.args[0] for c in
                  owner._bridge.set_core_state.call_args_list]
        self.assertIn("error", states)
        self.assertEqual(
            owner._bridge.set_core_state.call_count, 1,
            "mic error must be published once, not spamming",
        )
        subtitles = [c.args[0] for c in
                     owner._bridge.show_subtitle.call_args_list]
        self.assertEqual(len(subtitles), 1)
        # One restart attempt (shutdown+start), gated — not one per pass.
        mic.shutdown.assert_called_once_with()
        mic.start.assert_called_once_with()

    def test_dead_mic_skips_capture_never_listening(self) -> None:
        """The owner loop with a dead mic must never call capture or
        publish listening — it publishes error and keeps retrying."""
        owner = self._make_owner()
        mic = owner._microphone_stream
        mic.is_running = False
        duplex = owner._duplex_session
        owner._command_queue = queue.Queue()
        shutdown = threading.Event()
        owner._shutdown_in_progress = shutdown
        thread = threading.Thread(target=owner.run, daemon=True)
        thread.start()
        try:
            time.sleep(1.5)
            duplex.capture_command.assert_not_called()
            states = [c.args[0] for c in
                      owner._bridge.set_core_state.call_args_list]
            self.assertNotIn("listening", states)
            self.assertIn("error", states)
            self.assertTrue(thread.is_alive())
        finally:
            shutdown.set()
            owner._command_queue.put("exit")
            thread.join(timeout=5.0)

    def test_recovered_mic_clears_error_flag(self) -> None:
        owner = self._make_owner()
        mic = owner._microphone_stream
        mic.is_running = False
        owner._handle_listening_not_ready(owner._bridge)
        self.assertTrue(owner._mic_error_published)
        # Mic revived: readiness succeeds and re-arms the once-flag.
        mic.is_running = True
        mic.consumer_is.return_value = True
        mic.is_muted = False
        self.assertTrue(owner._ensure_listening_ready())
        self.assertFalse(owner._mic_error_published)


# ----------------------------------------------------------------------
# 5. TTS utterance hooks always pair (mute guard safety)
# ----------------------------------------------------------------------

class _FakeProvider:
    """Minimal provider: plays 0.2 s of 'audio', then goes idle."""

    def __init__(self) -> None:
        self._until = 0.0
        self.stopped = 0

    def speak(self, text: str) -> bool:
        self._until = time.monotonic() + 0.2
        return True

    def stop(self) -> None:
        self.stopped += 1
        self._until = 0.0

    @property
    def is_playing(self) -> bool:
        return time.monotonic() < self._until


class TestUtteranceHooks(unittest.TestCase):
    def test_started_finished_pair_around_utterance(self) -> None:
        manager = VoiceManager.__new__(VoiceManager)
        # Bypass provider auto-load; inject the fake directly.
        import queue as _queue
        import threading as _threading

        manager._settings = MagicMock()
        manager._diagnostics = []
        manager._queue = _queue.Queue()
        manager._queue_lock = _threading.Lock()
        manager._worker_thread = None
        manager._worker_start_lock = _threading.Lock()
        manager._stop_worker = _threading.Event()
        manager._current_text = None
        manager._interrupted = False
        manager._activity_lock = _threading.Lock()
        manager._pending_utterances = 0
        manager._speech_finished_event = _threading.Event()
        manager._speech_finished_event.set()
        manager.on_speech_finished = None
        calls: list[str] = []
        manager.on_utterance_started = lambda: calls.append("started")
        manager.on_utterance_finished = lambda: calls.append("finished")
        manager._provider = _FakeProvider()

        self.assertTrue(manager.speak("hello jarvis"))
        deadline = time.monotonic() + 10.0
        while manager.is_busy and time.monotonic() < deadline:
            time.sleep(0.02)

        self.assertFalse(manager.is_busy, "speech worker never finished")
        self.assertEqual(calls, ["started", "finished"])
        manager.shutdown()


if __name__ == "__main__":
    unittest.main()
