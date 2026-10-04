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

import math
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


class FakeWhisperSequence:
    """Returns a different segment list per transcribe call (for retry)."""

    def __init__(self, *batches) -> None:
        self._batches = list(batches)
        self.calls: list[dict] = []

    def transcribe(self, audio, **kwargs):
        self.calls.append(kwargs)
        index = min(len(self.calls) - 1, len(self._batches) - 1)
        return iter(self._batches[index]), object()


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
    # Energetic PCM (constant 4096 LSB, rms ~0.125): the recognizer
    # fast-fails near-silence without decoding, so tests must feed audio
    # with real energy — digital silence is "no speech", not a transcript.
    # (The fake model ignores content; only the energy gate sees it.)
    stt.push(b"\x00\x10" * 16000 * int(seconds))


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

        # VOICE-FIX: CPU-efficient final decode — small beam (<= 3;
        # beam 5 on CPU int8 costs seconds per utterance) + timestamps +
        # per-word probabilities, language pinned, no initial prompt
        # (avoids the prompt being echoed back as a fake transcript when
        # audio signal is weak — confirmed in production logs).
        # P0: vad_filter=False on the final — the external capture VAD owns
        # endpointing; the internal filter deleted whole accepted utterances
        # ("VAD filter removed 00:01.424" -> empty transcript).
        kwargs = factory.model.calls[0]
        self.assertEqual(kwargs["language"], "en")
        self.assertLessEqual(kwargs["beam_size"], 3)
        self.assertGreaterEqual(kwargs["beam_size"], 1)
        self.assertEqual(kwargs["temperature"], 0.0)
        self.assertEqual(kwargs["without_timestamps"], False)
        self.assertEqual(kwargs["word_timestamps"], True)
        self.assertIs(kwargs["vad_filter"], False)
        self.assertEqual(kwargs["condition_on_previous_text"], False)
        # Updated: initial_prompt now set with common commands for better recognition
        self.assertIn("Open YouTube", kwargs["initial_prompt"])

    def test_partial_decode_stays_fast_greedy(self) -> None:
        factory = _Factory([_Seg("hello world", avg_logprob=-0.1)])
        stt = WhisperRecognizer(
            model_factory=factory,
            enable_partials=True,
            partial_interval_ms=1.0,
        )
        stt.begin()
        stt.push(b"\x00\x00" * 16000)
        deadline = time.monotonic() + 3.0
        while not stt.partial_text() and time.monotonic() < deadline:
            time.sleep(0.02)
        self.assertEqual(stt.partial_text(), "hello world")

        partial_calls = [
            c for c in factory.model.calls if c.get("without_timestamps") is True
        ]
        self.assertTrue(partial_calls, "partials should use fast settings")
        for c in partial_calls:
            self.assertEqual(c["beam_size"], 1)
            self.assertEqual(c["word_timestamps"], False)
        stt.discard()

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

    def test_final_decode_receives_whole_buffer(self) -> None:
        """P0: the app must hand the decoder the ENTIRE capture buffer.

        Production showed "VAD filter removed 00:01.424" -> empty
        transcript for externally accepted speech.  With vad_filter=False
        on the final, faster-whisper cannot delete the utterance; this
        test pins the app side: full sample count delivered, filter off.
        """
        import numpy as np

        seen: dict = {}

        class WholeBufferWhisper(FakeWhisper):
            def transcribe(self, audio, **kwargs):
                seen["samples"] = len(np.asarray(audio).ravel())
                seen["kwargs"] = kwargs
                return super().transcribe(audio, **kwargs)

        factory = _Factory([_Seg("hello world", avg_logprob=-0.1)])
        factory.model = WholeBufferWhisper(factory._segments)
        stt = WhisperRecognizer(model_factory=factory, enable_partials=False)
        stt.begin()
        chunk = b"\x00\x10" * 16000  # 1.0 s energetic PCM
        stt.push(chunk)
        stt.push(chunk)  # 2.0 s total
        stt.finalize()
        self.assertEqual(seen["samples"], 32000)
        self.assertIs(seen["kwargs"]["vad_filter"], False)


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


class _Word:
    def __init__(self, word: str, probability: float) -> None:
        self.word = word
        self.probability = probability


class _SegWithWords(_Seg):
    def __init__(self, text: str, words, **kwargs) -> None:
        super().__init__(text, **kwargs)
        self.words = words


class TestWhisperPerWordConfidence(unittest.TestCase):
    def test_word_confidences_from_word_timestamps(self) -> None:
        segs = [
            _SegWithWords(
                "open chrome",
                words=[_Word("open", 0.95), _Word("chrome", 0.6)],
                start=0.0, end=1.0, avg_logprob=-0.1,
            )
        ]
        stt, _ = _make(segs)
        _feed(stt)
        final = stt.finalize()

        self.assertTrue(final.accepted)
        self.assertEqual(final.pass_used, "whisper")
        self.assertEqual(
            final.word_confidences, (("open", 0.95), ("chrome", 0.6))
        )
        self.assertAlmostEqual(final.min_word_confidence, 0.6, places=4)
        self.assertEqual(len(final.sentence_confidences), 1)
        self.assertEqual(final.sentence_confidences[0][0], "open chrome")

    def test_sentence_confidences_and_fallback_tokens(self) -> None:
        segs = [
            _Seg("open chrome", start=0.0, end=1.0, avg_logprob=-0.1),
            _Seg("now", start=1.0, end=2.0, avg_logprob=-0.3),
        ]
        stt, _ = _make(segs)
        _feed(stt)
        final = stt.finalize()

        # No .words on the fakes -> per-token fallback using segment confidence.
        self.assertEqual(len(final.word_confidences), 3)
        self.assertEqual(len(final.sentence_confidences), 2)
        self.assertEqual(final.min_word_confidence, math.exp(-0.3))

    def test_empty_transcript_has_no_word_metrics(self) -> None:
        stt, _ = _make([_Seg("ghost")])
        final = stt.finalize()
        self.assertEqual(final.word_confidences, ())
        self.assertEqual(final.sentence_confidences, ())
        self.assertIsNone(final.min_word_confidence)


class _SeqFactory:
    def __init__(self, seq: FakeWhisperSequence) -> None:
        self.model = seq

    def __call__(self):
        return self.model


class TestWhisperRetryPass(unittest.TestCase):
    def test_low_confidence_triggers_retry_that_rescues(self) -> None:
        factory = _SeqFactory(
            FakeWhisperSequence(
                [_Seg("chrome", avg_logprob=-2.0)],  # pass 1: low confidence
                [_Seg("open chrome", avg_logprob=-0.1)],  # retry: rescued
            )
        )
        stt = WhisperRecognizer(model_factory=factory, enable_partials=False)
        stt.begin()
        _feed(stt)
        final = stt.finalize()

        self.assertTrue(final.accepted)
        self.assertEqual(final.text, "open chrome")
        self.assertEqual(final.pass_used, "whisper-retry")
        self.assertEqual(len(factory.model.calls), 2)

        retry_kwargs = factory.model.calls[1]
        self.assertEqual(retry_kwargs["temperature"], 0.2)
        self.assertIs(retry_kwargs["vad_filter"], False)
        self.assertIsNone(retry_kwargs["initial_prompt"])

    def test_no_retry_when_accepted(self) -> None:
        segs = [_Seg("open chrome", avg_logprob=-0.1)]
        stt, factory = _make(segs)
        _feed(stt)
        final = stt.finalize()

        self.assertTrue(final.accepted)
        self.assertEqual(final.pass_used, "whisper")
        self.assertEqual(len(factory.model.calls), 1)

    def test_retry_does_not_rescue_hopeless_low_confidence(self) -> None:
        segs = [_Seg("chrome", avg_logprob=-2.0)]
        stt, factory = _make(segs)
        _feed(stt)
        final = stt.finalize()

        self.assertFalse(final.accepted)
        self.assertEqual(final.rejected_reason, "low confidence")
        self.assertEqual(final.pass_used, "whisper")  # retry did not improve
        self.assertEqual(len(factory.model.calls), 2)

    def test_no_retry_on_blip_audio(self) -> None:
        """FIX 4: re-decoding a 0.1 s blip cannot rescue it — skip the
        second full decode and keep the original rejection."""
        segs = [_Seg("chrome", avg_logprob=-2.0)]
        stt, factory = _make(segs)
        _feed(stt)
        final = stt.finalize(voiced_seconds=0.1)

        self.assertFalse(final.accepted)
        self.assertEqual(final.rejected_reason, "low confidence")
        self.assertEqual(
            len(factory.model.calls), 1,
            "blip audio must not trigger the retry decode",
        )


if __name__ == "__main__":
    unittest.main()
