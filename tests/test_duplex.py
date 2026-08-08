"""
tests/test_duplex.py

Unit tests for voice/duplex.py — the full-duplex voice coordinator:

  * streaming capture via ``capture_command`` (pre-roll, partials,
    confidence-gated finals, pause-tolerant re-listen),
  * instant barge-in on echo-cancelled user speech,
  * wake-word routing (incl. wake-during-speech -> barge-in).

Voice modules only capture audio — they never decide conversation state.
Conversation state is owned exclusively by ``services.conversation_owner``.

No real Vosk, microphone, or TTS is used: a fake transcriber, passthrough
DSP, and fake wake detector are injected.
"""

from __future__ import annotations

import threading
import time
import unittest

from voice.duplex import DuplexVoiceSession, CaptureResult
from voice.streaming_stt import FinalTranscript


class PassthroughDSP:
    def process(self, chunk: bytes) -> bytes:
        return chunk

    def set_reference(self, chunk: bytes, sample_rate: int = 16000) -> None:
        pass


class FakeTranscriber:
    def __init__(self, final: FinalTranscript) -> None:
        self._final = final
        self.started = 0
        self.pushed: list[bytes] = []
        self.discarded = False
        self.reset_count = 0
        self._finished = False

    def begin(self) -> None:
        self.started += 1
        self._finished = False

    def push(self, chunk: bytes) -> None:
        self.pushed.append(chunk)

    def partial_text(self) -> str:
        return ""

    def finalize(self) -> FinalTranscript:
        self._finished = True
        return self._final

    def discard(self) -> None:
        self.discarded = True
        self._finished = True

    def reset(self) -> None:
        self.reset_count += 1


class NoAudioTranscriber(FakeTranscriber):
    """Finalize always reports that no speech was recognized."""

    def finalize(self) -> FinalTranscript:
        self._finished = True
        return FinalTranscript("", 0.0, False, 0.0, "no speech recognized")


class FakeVAD:
    """Lightweight stand-in for the capture/barge-in VADs (avoids loading
    the torch-backed Silero model in unit tests)."""

    def __init__(self) -> None:
        self.processed: list[bytes] = []
        self.reset_count = 0
        self._triggered = False

    def process_audio(self, chunk: bytes) -> None:
        self.processed.append(chunk)

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


class FakeWakeDetector:
    def __init__(self) -> None:
        self.chunks: list[bytes] = []
        self.reset_count = 0

    def process_audio(self, chunk: bytes) -> None:
        self.chunks.append(chunk)

    def reset(self) -> None:
        self.reset_count += 1


def _make_session(
    final: FinalTranscript | None = None,
    on_partial=None,
    on_wake_word=None,
    on_barge_in=None,
) -> tuple[DuplexVoiceSession, FakeTranscriber]:
    transcriber = FakeTranscriber(
        final or FinalTranscript("open notepad", 0.9, True, duration_ms=1200.0)
    )
    session = DuplexVoiceSession(
        sample_rate=16000,
        echo_canceller=PassthroughDSP(),  # type: ignore[arg-type]
        noise_suppressor=PassthroughDSP(),  # type: ignore[arg-type]
        transcriber=transcriber,  # type: ignore[arg-type]
        on_partial=on_partial,
        on_wake_word=on_wake_word,
        on_barge_in=on_barge_in,
        silence_hangover_ms=500.0,
        max_capture_timeout=30.0,
        capture_vad=FakeVAD(),  # type: ignore[arg-type]
        barge_in_vad=FakeVAD(),  # type: ignore[arg-type]
    )
    return session, transcriber


def _feed_events(session, events, delay: float = 0.05) -> None:
    """Feed capture events shortly AFTER capture_command() starts.

    The redesigned capture drains the event queue at entry, so events must
    arrive while the capture is actually listening (as they do in production
    from the microphone thread).
    """
    def run() -> None:
        time.sleep(delay)
        for event in events:
            session._events.put(event)
            time.sleep(0.02)
    threading.Thread(target=run, daemon=True).start()


def _speech_events() -> list[tuple]:
    return [
        ("speech_start", time.monotonic()),
        ("speech_end", time.monotonic()),
    ]


class TestDuplexCapture(unittest.TestCase):
    def test_capture_returns_accepted_command(self) -> None:
        session, transcriber = _make_session()
        _feed_events(session, _speech_events())

        result = session.capture_command(timeout=2.0)

        self.assertIsInstance(result, CaptureResult)
        self.assertTrue(result.accepted)
        self.assertTrue(result.success)
        self.assertEqual(result.text, "open notepad")
        self.assertEqual(transcriber.started, 1)

    def test_capture_waits_for_speech_before_starting_timeout(self) -> None:
        """A late speech onset is still captured — the idle timer only starts
        timing the *wait*, not the user's first word (Requirement #1/#2)."""
        session, transcriber = _make_session()
        # Speech arrives 0.25s in; a short 0.3s idle timeout must still let it
        # through once onset is detected.
        _feed_events(session, _speech_events(), delay=0.15)

        result = session.capture_command(timeout=0.4)

        self.assertTrue(result.success)
        self.assertEqual(result.text, "open notepad")

    def test_capture_rejects_low_confidence_and_reports_reason(self) -> None:
        rejected = FinalTranscript("noise", 0.2, False, duration_ms=500.0, rejected_reason="low confidence")
        session, transcriber = _make_session(final=rejected)
        _feed_events(session, _speech_events())

        result = session.capture_command(timeout=2.0)

        self.assertFalse(result.accepted)
        self.assertEqual(result.reason, "low confidence")
        self.assertEqual(result.text, "noise")
        # No silent re-listen inside the capture: the caller decides the
        # retry prompt and calls capture again (Requirement #6/#7/#8).
        self.assertEqual(transcriber.started, 1)

    def test_capture_timeout_with_no_speech_returns_no_speech(self) -> None:
        transcriber = NoAudioTranscriber(
            FinalTranscript("open notepad", 0.9, True, duration_ms=1200.0)
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
        result = session.capture_command(timeout=0.1)
        self.assertFalse(result.accepted)
        self.assertEqual(result.reason, "no_speech")
        self.assertEqual(result.text, "")

    def test_capture_streams_partials_to_callback(self) -> None:
        partials: list[str] = []
        session, _ = _make_session()
        _feed_events(session, [
            ("partial", "hello wor"),
            ("partial", "hello world"),
            ("speech_start", time.monotonic()),
            ("speech_end", time.monotonic()),
        ])

        result = session.capture_command(timeout=2.0, on_partial=partials.append)

        self.assertEqual(partials, ["hello wor", "hello world"])
        self.assertTrue(result.accepted)

    def test_capture_cancel(self) -> None:
        session, transcriber = _make_session()
        session.cancel_capture()
        self.assertTrue(transcriber.discarded)


class TestDuplexPreroll(unittest.TestCase):
    def test_preroll_seeds_transcriber_on_begin(self) -> None:
        session, transcriber = _make_session()
        session._append_preroll(b"\x01\x00" * 1000)
        session._append_preroll(b"\x02\x00" * 1000)
        _feed_events(session, _speech_events())

        session.capture_command(timeout=2.0)

        self.assertTrue(transcriber.pushed)
        self.assertEqual(
            transcriber.pushed[0],
            b"\x01\x00" * 1000 + b"\x02\x00" * 1000,
        )


class TestDuplexBargeIn(unittest.TestCase):
    def test_onset_while_speaking_triggers_interrupt(self) -> None:
        fired: list[str] = []
        session, _ = _make_session(on_barge_in=lambda: fired.append("barge"))
        session.arm_barge_in()

        session._on_barge_in_onset()

        self.assertEqual(fired, ["barge"])

    def test_onset_while_disarmed_does_not_fire(self) -> None:
        fired: list[str] = []
        session, _ = _make_session(on_barge_in=lambda: fired.append("barge"))
        session._on_barge_in_onset()

        self.assertEqual(fired, [])

    def test_disarm_stops_barge_in(self) -> None:
        fired: list[str] = []
        session, _ = _make_session(on_barge_in=lambda: fired.append("barge"))
        session.arm_barge_in()
        session.disarm_barge_in()

        session._on_barge_in_onset()

        self.assertEqual(fired, [])


class TestDuplexWakeWord(unittest.TestCase):
    def test_wake_armed_feeds_detector(self) -> None:
        session, _ = _make_session()
        detector = FakeWakeDetector()
        session._wake_detector = detector  # type: ignore[assignment]

        session.start_wake_detection()
        session.process_chunk(b"\x01\x00" * 64)

        self.assertEqual(len(detector.chunks), 1)

    def test_wake_while_idle_calls_callback(self) -> None:
        heard: list[object] = []
        session, _ = _make_session(on_wake_word=heard.append)
        session.start_wake_detection()

        session._on_wake_word_detected(b"wake-audio")

        self.assertEqual(heard, [b"wake-audio"])

    def test_wake_while_speaking_triggers_barge_in(self) -> None:
        heard: list[object] = []
        interrupted: list[str] = []
        session, _ = _make_session(
            on_wake_word=heard.append,
            on_barge_in=lambda: interrupted.append("barge"),
        )
        session.arm_barge_in()

        session._on_wake_word_detected(b"wake-audio")

        self.assertEqual(heard, [])
        self.assertEqual(interrupted, ["barge"])

    def test_reset_wake_uses_detector(self) -> None:
        session, _ = _make_session()
        detector = FakeWakeDetector()
        session._wake_detector = detector  # type: ignore[assignment]

        session.reset_wake()

        self.assertEqual(detector.reset_count, 1)


class TestDuplexCanonicalization(unittest.TestCase):
    """FIX-002: the synonym engine canonicalises accepted text and the
    capture result exposes raw/canonical text, the pass used, and the
    Speech End -> Recognition Finished latency."""

    def _capture(self, final: FinalTranscript) -> CaptureResult:
        session, _ = _make_session(final=final)
        _feed_events(session, _speech_events())
        return session.capture_command(timeout=2.0)

    def test_canonicalizes_synonym_phrases(self) -> None:
        final = FinalTranscript("start music", 0.9, True, duration_ms=800.0)
        result = self._capture(final)
        self.assertEqual(result.text, "play music")
        self.assertEqual(result.raw_text, "start music")
        self.assertEqual(result.canonical_text, "play music")
        self.assertTrue(result.accepted)

    def test_no_change_keeps_text_and_no_canonical(self) -> None:
        final = FinalTranscript("open notepad", 0.9, True, duration_ms=800.0)
        result = self._capture(final)
        self.assertEqual(result.text, "open notepad")
        self.assertEqual(result.canonical_text, "")
        self.assertEqual(result.raw_text, "open notepad")

    def test_rejected_final_is_not_canonicalized(self) -> None:
        final = FinalTranscript(
            "start music", 0.3, False, duration_ms=800.0,
            rejected_reason="low confidence",
        )
        result = self._capture(final)
        self.assertFalse(result.accepted)
        self.assertEqual(result.reason, "low confidence")
        self.assertEqual(result.text, "start music")
        self.assertEqual(result.canonical_text, "")

    def test_pass_used_and_recognition_latency_recorded(self) -> None:
        final = FinalTranscript(
            "open notepad", 0.9, True, duration_ms=800.0, pass_used="pass2",
        )
        result = self._capture(final)
        self.assertEqual(result.pass_used, "pass2")
        self.assertGreaterEqual(result.recognition_ms, 0.0)


if __name__ == "__main__":
    unittest.main()