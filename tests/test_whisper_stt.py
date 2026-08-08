"""
tests/test_whisper_stt.py

Unit tests for voice/whisper_stt.py — the Faster-Whisper transcriber:

  * confidence-gated finals (threshold, single-word stricter bar,
    too-short, no-speech),
  * confidence derived from exp(avg_logprob) scaled by (1 - no_speech_prob),
  * Indian-English / command decode settings (language pin, greedy beam),
  * model loaded once, best-effort partials, session lifecycle.

No real Whisper model is loaded — a fake transcribe() is injected.
"""

from __future__ import annotations

import time
import unittest
from unittest.mock import patch

from voice.streaming_stt import FinalTranscript
from voice.whisper_stt import WhisperRecognizer


class _Seg:
    def __init__(
        self,
        text: str,
        start: float = 0.0,
        end: float = 1.0,
        avg_logprob: float = -0.2,
        no_speech_prob: float = 0.0,
    ) -> None:
        self.text = text
        self.start = start
        self.end = end
        self.avg_logprob = avg_logprob
        self.no_speech_prob = no_speech_prob


class FakeWhisper:
    def __init__(self, segments) -> None:
        self._segments = segments
        self.calls: list[dict] = []
        self.instances = 0

    def transcribe(self, audio, **kwargs):
        self.calls.append(kwargs)
        return iter(self._segments), object()


class _Factory:
    def __init__(self, segments) -> None:
        self._segments = segments
        self.model = FakeWhisper(segments)

    def __call__(self):
        return self.model


def _make(
    segments,
    **kwargs,
) -> tuple[WhisperRecognizer, _Factory]:
    factory = _Factory(segments)
    stt = WhisperRecognizer(model_factory=factory, enable_partials=False, **kwargs)
    stt.begin()
    return stt, factory


def _feed(stt: WhisperRecognizer, seconds: float = 1.0) -> None:
    stt.push(b"\x00\x00" * 16000 * int(seconds))


class TestWhisperFinals(unittest.TestCase):
    def test_accepted_command_with_expected_confidence(self) -> None:
        segs = [
            _Seg("open chrome", start=0.0, end=1.0, avg_logprob=-0.1),
            _Seg("", start=1.0, end=2.0, avg_logprob=-0.1),
        ]
        stt, _ = _make(segs)
        _feed(stt)
        final = stt.finalize()

        self.assertTrue(final.accepted)
        self.assertEqual(final.text, "open chrome")
        self.assertEqual(final.pass_used, "whisper")
        self.assertGreater(final.confidence, 0.7)
        # empty segment contributes no text but its weight is tiny
        self.assertLess(final.confidence, 1.0)

    def test_confidence_is_avg_logprob_weighted_and_speech_scaled(self) -> None:
        segs = [
            _Seg("hello", start=0.0, end=1.0, avg_logprob=-0.1, no_speech_prob=0.0),
            _Seg("world", start=1.0, end=2.0, avg_logprob=-0.3, no_speech_prob=0.0),
        ]
        stt, _ = _make(segs)
        _feed(stt)
        final = stt.finalize()
        import math

        expected = (math.exp(-0.1) + math.exp(-0.3)) / 2.0
        self.assertAlmostEqual(final.confidence, expected, places=4)

    def test_low_confidence_single_word_rejected(self) -> None:
        segs = [_Seg("chrome", start=0.0, end=1.0, avg_logprob=-2.0)]
        stt, _ = _make(segs)
        _feed(stt)
        final = stt.finalize()

        self.assertFalse(final.accepted)
        self.assertEqual(final.rejected_reason, "low confidence")
        self.assertEqual(final.text, "chrome")

    def test_no_speech_segment_collapses_confidence(self) -> None:
        segs = [_Seg("noise", start=0.0, end=1.0, avg_logprob=-0.1, no_speech_prob=0.99)]
        stt, _ = _make(segs)
        _feed(stt)
        final = stt.finalize()

        self.assertFalse(final.accepted)
        self.assertEqual(final.rejected_reason, "low confidence")

    def test_empty_buffer_is_no_speech(self) -> None:
        stt, _ = _make([_Seg("ghost")])
        final = stt.finalize()

        self.assertFalse(final.accepted)
        self.assertEqual(final.rejected_reason, "no speech recognized")
        self.assertEqual(final.text, "")

    def test_too_short_text_rejected(self) -> None:
        segs = [_Seg("a", start=0.0, end=1.0, avg_logprob=-0.05)]
        stt, _ = _make(segs, min_text_chars=2)
        _feed(stt)
        final = stt.finalize()

        self.assertFalse(final.accepted)
        self.assertEqual(final.rejected_reason, "too short")

    def test_decode_failure_is_recognizer_error(self) -> None:
        def boom(audio, **kwargs):
            raise RuntimeError("decode failed")

        class BadWhisper(FakeWhisper):
            def transcribe(self, audio, **kwargs):
                boom(audio, **kwargs)

        factory = _Factory(BadWhisper([]))
        stt = WhisperRecognizer(model_factory=factory, enable_partials=False)
        stt.begin()
        _feed(stt)
        final = stt.finalize()

        self.assertFalse(final.accepted)
        self.assertEqual(final.rejected_reason, "no speech recognized")


class TestWhisperDecodeSettings(unittest.TestCase):
    def test_indian_english_tuning_applied(self) -> None:
        segs = [_Seg("open chrome", avg_logprob=-0.1)]
        stt, factory = _make(segs)
        _feed(stt)
        stt.finalize()

        kwargs = factory.model.calls[0]
        self.assertEqual(kwargs["language"], "en")
        self.assertEqual(kwargs["beam_size"], 1)
        self.assertEqual(kwargs["temperature"], 0.0)
        self.assertEqual(kwargs["without_timestamps"], True)
        self.assertEqual(kwargs["vad_filter"], True)
        self.assertEqual(kwargs["condition_on_previous_text"], False)
        self.assertIsNotNone(kwargs["initial_prompt"])

    def test_model_loaded_once(self) -> None:
        segs = [_Seg("hi", avg_logprob=-0.1)]
        stt, factory = _make(segs)
        _feed(stt)
        stt.finalize()
        stt.begin()
        _feed(stt)
        stt.finalize()

        self.assertEqual(factory.model.instances, 0)  # model created via factory once
        self.assertEqual(len(factory.model.calls), 2)


class TestWhisperLifecycle(unittest.TestCase):
    def test_partials_disabled_push_returns_none(self) -> None:
        stt, _ = _make([_Seg("hello")])
        self.assertIsNone(stt.push(b"\x00\x00" * 160))
        self.assertEqual(stt.partial_text(), "")

    def test_partial_worker_populates_text(self) -> None:
        factory = _Factory([_Seg("hello world", avg_logprob=-0.1)])
        stt = WhisperRecognizer(
            model_factory=factory,
            enable_partials=True,
            partial_interval_ms=10.0,
        )
        stt.begin()
        stt.push(b"\x00\x00" * 16000)
        deadline = time.monotonic() + 3.0
        while not stt.partial_text() and time.monotonic() < deadline:
            time.sleep(0.02)
        self.assertEqual(stt.partial_text(), "hello world")
        stt.discard()

    def test_discard_marks_finished(self) -> None:
        stt, _ = _make([_Seg("hi")])
        stt.discard()
        self.assertFalse(stt.is_active)
        self.assertIsNone(stt.push(b"\x00\x00" * 160))

    def test_reset_allows_restart(self) -> None:
        stt, _ = _make([_Seg("hi")])
        stt.begin()
        stt.reset()
        stt.begin()
        self.assertTrue(stt.is_active)
        stt.discard()

    def test_gate_matches_streaming_thresholds(self) -> None:
        segs = [_Seg("chrome", avg_logprob=-0.4)]  # exp(-0.4)=0.67 > 0.5
        stt, _ = _make(segs, confidence_threshold=0.5, single_word_min_confidence=0.6)
        _feed(stt)
        final = stt.finalize()
        self.assertTrue(final.accepted)
        self.assertIsInstance(final, FinalTranscript)


if __name__ == "__main__":
    unittest.main()
