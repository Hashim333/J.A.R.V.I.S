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

    def finalize(self, voiced_seconds: float | None = None) -> FinalTranscript:
        self._finished = True
        return self._final

    def discard(self) -> None:
        self.discarded = True
        self._finished = True

    def reset(self) -> None:
        self.reset_count += 1


class NoAudioTranscriber(FakeTranscriber):
    """Finalize always reports that no speech was recognized."""

    def finalize(self, voiced_seconds: float | None = None) -> FinalTranscript:
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
    """A short but realistic utterance onset/end (~0.8s voiced)."""
    now = time.monotonic()
    return [
        ("speech_start", now - 0.8),
        ("speech_end", now),
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

    def test_capture_discards_too_short_before_stt(self) -> None:
        """FIX-VOICE-005: a ~0.03s VAD blip is discarded BEFORE Whisper/STT —
        no finalize, no hallucinated text; the capture just returns 'too short'."""
        session, transcriber = _make_session()
        now = time.monotonic()
        _feed_events(session, [
            ("speech_start", now - 0.03),
            ("speech_end", now),
        ])

        result = session.capture_command(timeout=2.0)

        self.assertFalse(result.accepted)
        self.assertEqual(result.reason, "too short")
        self.assertEqual(result.text, "")
        self.assertTrue(transcriber.discarded)

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
            ("speech_start", time.monotonic() - 0.8),
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

    def test_arm_barge_in_is_idempotent(self) -> None:
        """FIX-001: the conversation loop re-arms barge-in every ~50 ms while
        speaking; a reset on each call cleared the VAD onset accumulator so
        instant barge-in never fired.  Arming while already armed must not
        reset the detector."""
        session, _ = _make_session()
        session.arm_barge_in()
        resets_after_first_arm = session._barge_in_vad.reset_count

        session.arm_barge_in()

        self.assertEqual(session._barge_in_vad.reset_count, resets_after_first_arm)


class TestDuplexWakeWord(unittest.TestCase):
    def test_wake_armed_feeds_detector(self) -> None:
        session, _ = _make_session()
        detector = FakeWakeDetector()
        session._wake_detector = detector  # type: ignore[assignment]

        session.start_wake_detection()
        session.process_chunk(b"\x01\x00" * 64)

        self.assertEqual(len(detector.chunks), 1)

    def test_wake_not_fed_detector_while_capturing(self) -> None:
        """FIX-001: the Vosk wake check is suspended during capture so it
        cannot starve the microphone thread mid-command (which clipped the
        audio and caused phantom 'didn't understand' responses)."""
        session, _ = _make_session()
        detector = FakeWakeDetector()
        session._wake_detector = detector  # type: ignore[assignment]

        session.start_wake_detection()
        session._in_capture = True
        session.process_chunk(b"\x01\x00" * 64)

        self.assertEqual(len(detector.chunks), 0)

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

    def test_start_wake_rearm_cooldown_defers_detector_feed(self) -> None:
        """FIX-NO-WAKE-ECHO: after returning to idle, the wake detector must
        not be fed mic audio for the re-arm cooldown window — a residual
        wake-phrase echo from JARVIS's own last utterance cannot re-trigger
        the moment the detector is re-armed."""
        session, _ = _make_session()
        detector = FakeWakeDetector()
        session._wake_detector = detector  # type: ignore[assignment]
        session._wake_rearm_until = time.monotonic() + 0.4

        session.process_chunk(b"\x01\x00" * 64)

        self.assertEqual(len(detector.chunks), 0,
                         "detector fed during re-arm cooldown")

    def test_start_wake_cooldown_expires_and_feeds_detector(self) -> None:
        session, _ = _make_session()
        detector = FakeWakeDetector()
        session._wake_detector = detector  # type: ignore[assignment]
        session._wake_armed = True
        session._wake_rearm_until = time.monotonic() - 0.1

        session.process_chunk(b"\x01\x00" * 64)

        self.assertEqual(len(detector.chunks), 1,
                         "detector never resumed after cooldown")


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


class TestDuplexPerWordConfidence(unittest.TestCase):
    """FIX-003: per-word / per-sentence confidence and the Phase-A idle wait
    are carried on the CaptureResult for the Speech Intelligence Layer."""

    def test_word_confidences_propagate_to_capture_result(self) -> None:
        final = FinalTranscript(
            "open chrome", 0.9, True, duration_ms=800.0,
            word_confidences=(("open", 0.95), ("chrome", 0.6)),
            sentence_confidences=(("open chrome", 0.9),),
            min_word_confidence=0.6,
        )
        session, _ = _make_session(final=final)
        _feed_events(session, _speech_events(), delay=0.15)

        result = session.capture_command(timeout=2.0)

        self.assertEqual(result.word_confidences, (("open", 0.95), ("chrome", 0.6)))
        self.assertEqual(result.sentence_confidences, (("open chrome", 0.9),))
        self.assertAlmostEqual(result.min_word_confidence, 0.6, places=4)
        self.assertGreater(result.idle_wait_ms, 0.0)

    def test_absent_word_metrics_default_to_empty(self) -> None:
        final = FinalTranscript("open notepad", 0.9, True, duration_ms=800.0)
        session, _ = _make_session(final=final)
        _feed_events(session, _speech_events())

        result = session.capture_command(timeout=2.0)

        self.assertEqual(result.word_confidences, ())
        self.assertEqual(result.sentence_confidences, ())
        self.assertIsNone(result.min_word_confidence)


class TestCaptureCallbackClamp(unittest.TestCase):
    """PART 14: a slow inline ``on_partial`` must never stall the mic thread.
    One overrun switches off inline invocation (queue delivery continues)."""

    def _in_capture(self, session, transcriber) -> None:
        # Make the transcriber emit a partial on every pushed chunk and put
        # the session into capture so ``process_chunk`` routes to
        # ``_feed_capture``.
        def push(chunk: bytes) -> str:
            transcriber.pushed.append(chunk)
            return "open "
        transcriber.push = push  # type: ignore[method-assign]
        session._in_capture = True
        session._capture_started = True
        session._capture_vad._triggered = True

    def test_slow_partial_callback_is_disabled_after_overrun(self) -> None:
        session, transcriber = _make_session(
            final=FinalTranscript("open notepad", 0.9, True, duration_ms=800.0),
        )
        calls = [0]
        session.on_partial = _SlowPartial(calls, slow_first=True)
        self._in_capture(session, transcriber)

        # Feed two chunks directly on the "mic thread".
        session.process_chunk(b"\x01\x00" * 64)
        session.process_chunk(b"\x01\x00" * 64)

        self.assertEqual(calls[0], 1, "the second call must be clamped away")
        self.assertEqual(session._partial_callback_overruns, 1)

    def test_fast_partial_callback_stays_enabled(self) -> None:
        session, transcriber = _make_session(
            final=FinalTranscript("open notepad", 0.9, True, duration_ms=800.0),
        )
        calls = [0]
        session.on_partial = _SlowPartial(calls, slow_first=False)
        self._in_capture(session, transcriber)

        session.process_chunk(b"\x01\x00" * 64)
        session.process_chunk(b"\x01\x00" * 64)

        self.assertEqual(calls[0], 2, "fast callbacks are never clamped")
        self.assertEqual(session._partial_callback_overruns, 0)


class TestCaptureFinalizeHardLimit(unittest.TestCase):
    """PART 15: a stuck recognizer must never wedge capture_command."""

    def test_hung_finalize_returns_speech_timeout(self) -> None:
        import voice.duplex as duplex_mod

        session, _ = _make_session(
            final=FinalTranscript("open notepad", 0.9, True, duration_ms=800.0),
        )
        # Finalize blocks forever once speech ends -> the hard limit must
        # bail out instead of hanging the test.  Shorten the ceiling so the
        # test stays fast.
        original = duplex_mod._MAX_FINALIZE_SECONDS
        duplex_mod._MAX_FINALIZE_SECONDS = 0.3
        try:
            session._transcriber.finalize = _hang()  # type: ignore[assignment]
            session._max_capture_timeout = 1.0  # keep Phase B short
            _feed_events(session, _speech_events(), delay=0.15)

            started = time.monotonic()
            result = session.capture_command(timeout=2.0)
            elapsed = time.monotonic() - started
        finally:
            duplex_mod._MAX_FINALIZE_SECONDS = original

        self.assertLess(elapsed, 30.0, "capture must not hang on finalize")
        self.assertFalse(result.accepted)


class TestDefaultTranscriber(unittest.TestCase):
    """VOICE-PIPELINE-006: the runtime transcriber must finalize each
    utterance exactly once.  A background partial decoder re-decodes the
    whole growing capture buffer on a loop and holds ``_decode_lock``, which
    starves the authoritative ``finalize()`` past the 20 s hard limit; the
    default must therefore build the transcriber with partials disabled."""

    def test_default_transcriber_has_partials_disabled(self) -> None:
        session = DuplexVoiceSession(
            sample_rate=16000,
            echo_canceller=PassthroughDSP(),  # type: ignore[arg-type]
            noise_suppressor=PassthroughDSP(),  # type: ignore[arg-type]
            silence_hangover_ms=500.0,
            capture_vad=FakeVAD(),  # type: ignore[arg-type]
            barge_in_vad=FakeVAD(),  # type: ignore[arg-type]
        )
        self.assertFalse(
            session._transcriber._enable_partials,
            "default transcriber must not run the background partial decoder",
        )


class _SlowPartial:
    """on_partial callback that (optionally) exceeds the clamp ceiling once."""

    def __init__(self, calls: list, slow_first: bool) -> None:
        self._calls = calls
        self._slow_first = slow_first

    def __call__(self, text: str) -> None:
        if self._slow_first and self._calls[0] == 0:
            time.sleep(0.6)  # > _MAX_PARTIAL_CALLBACK_SECONDS (0.5 s)
        self._calls[0] += 1


def _hang():
    """Return a finalize replacement that blocks until cancelled."""
    def finalize(voiced_seconds=None):
        stop = threading.Event()
        stop.wait(60.0)
        return FinalTranscript("", 0.0, False, 0.0, "no speech recognized")
    return finalize


class TestOnsetEnergyGate(unittest.TestCase):
    """FIX 4: VAD frame votes alone fire on clicks/transients — an onset
    without speech-like post-gate energy must reset the VAD and emit
    nothing instead of burning a capture + Whisper decode."""

    def test_flat_noise_onset_rejected_and_vad_reset(self) -> None:
        session, _ = _make_session()
        session._drain_events()
        session._in_capture = True  # route mic chunks into _feed_capture
        resets_before = session._capture_vad.reset_count
        # Flat room noise (rms ~6e-5, far below any speech floor).
        for _ in range(12):
            session.process_chunk(b"\x02\x00" * 512)
        session._on_capture_speech_started()
        self.assertTrue(
            session._events.empty(),
            "flat-noise onset must not emit speech_start",
        )
        self.assertGreater(
            session._capture_vad.reset_count, resets_before,
            "rejected onset must re-arm the VAD for real speech",
        )

    def test_energetic_onset_accepted(self) -> None:
        session, _ = _make_session()
        session._drain_events()
        # Loud burst (rms 0.25) — unambiguous speech energy.
        for _ in range(12):
            session.process_chunk(b"\x00\x20" * 512)
        session._on_capture_speech_started()
        kind, *_ = session._events.get_nowait()
        self.assertEqual(kind, "speech_start")

    def test_no_audio_observed_fails_open(self) -> None:
        """Direct event injection (no mic audio) must keep working."""
        session, _ = _make_session()
        session._drain_events()
        session._on_capture_speech_started()
        kind, *_ = session._events.get_nowait()
        self.assertEqual(kind, "speech_start")

    def test_soft_speech_in_quiet_room_accepted(self) -> None:
        session, _ = _make_session()
        session._drain_events()
        # Near-silence background (rms ~6e-5), faint murmur (rms ~6e-4),
        # then soft speech (rms ~0.031) — the absolute clause accepts it.
        for _ in range(8):
            session.process_chunk(b"\x02\x00" * 512)
        for _ in range(8):
            session.process_chunk(b"\x14\x00" * 512)
        for _ in range(8):
            session.process_chunk(b"\x00\x04" * 512)
        session._on_capture_speech_started()
        kind, *_ = session._events.get_nowait()
        self.assertEqual(kind, "speech_start")


if __name__ == "__main__":
    unittest.main()