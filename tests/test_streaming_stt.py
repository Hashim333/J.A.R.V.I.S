"""
tests/test_streaming_stt.py

Unit tests for voice/streaming_stt.py — streaming partial transcripts,
confidence-gated finals, and segment accumulation.

A fake Vosk recognizer is injected so no model download or audio
hardware is required.
"""

from __future__ import annotations

import json
import unittest
import unittest.mock

from voice.streaming_stt import (
    FinalTranscript,
    MAX_CONSECUTIVE_ERRORS,
    StreamingTranscriber,
    preload_model,
)


class FakeRecognizer:
    """Vosk-compatible recognizer driven by scripted results.

    Args:
        partial: Partial transcript returned by PartialResult().
        final_text / final_confidence: Value returned by FinalResult()
            unless ``finals`` is given.
        force_final_on_chunk: Chunk index(es) (1-based) on which
            AcceptWaveform returns True.  Int or iterable of ints.
        include_confidence: When False, FinalResult() omits the confidence
            field (simulates a recognizer that reports none).
        finals: Optional queue of ``(text, confidence)`` finals consumed one
            per forced final — used to script multi-segment results.
        raise_on_accept: When True, AcceptWaveform always raises (simulates
            a broken recognizer).
    """

    def __init__(
        self,
        partial: str = "",
        final_text: str = "",
        final_confidence: float = 0.9,
        force_final_on_chunk: int | object | None = None,
        include_confidence: bool = True,
        finals: list[tuple[str, float]] | None = None,
        raise_on_accept: bool = False,
    ) -> None:
        self.partial = partial
        self.final_text = final_text
        self.final_confidence = final_confidence
        if isinstance(force_final_on_chunk, int):
            self._force = {force_final_on_chunk}
        else:
            self._force = set(force_final_on_chunk or ())
        self.include_confidence = include_confidence
        self.finals = list(finals) if finals else None
        self.raise_on_accept = raise_on_accept
        self.chunk_index = 0
        self.final_calls = 0
        self.accepted_waveforms = 0

    def AcceptWaveform(self, chunk: bytes) -> bool:  # noqa: N802
        self.accepted_waveforms += 1
        self.chunk_index += 1
        if self.raise_on_accept:
            raise RuntimeError("broken recognizer")
        return self.chunk_index in self._force

    def PartialResult(self) -> str:  # noqa: N802
        return json.dumps({"partial": self.partial})

    def FinalResult(self) -> str:  # noqa: N802
        self.final_calls += 1
        if self.finals is not None:
            if self.finals:
                text, conf = self.finals.pop(0)
                return json.dumps({"text": text, "confidence": conf})
            return json.dumps({"text": "", "confidence": 0.0})
        data = {"text": self.final_text}
        if self.include_confidence:
            data["confidence"] = self.final_confidence
        return json.dumps(data)


class _CountingFactory:
    def __init__(self, recognizer: FakeRecognizer) -> None:
        self.recognizer = recognizer
        self.calls = 0

    def __call__(self) -> FakeRecognizer:
        self.calls += 1
        return self.recognizer


class _TwoPassFactory:
    """Returns a distinct recognizer per call (call 1 = Pass 1, call 2+ = Pass 2)."""

    def __init__(self, pass1: FakeRecognizer, pass2: FakeRecognizer) -> None:
        self._recognizers = [pass1, pass2]
        self.calls = 0

    def __call__(self) -> FakeRecognizer:
        recognizer = self._recognizers[min(self.calls, len(self._recognizers) - 1)]
        self.calls += 1
        return recognizer


class TestStreamingTranscriberPartials(unittest.TestCase):
    def test_push_returns_none_before_begin(self) -> None:
        stt = StreamingTranscriber(recognizer_factory=lambda: FakeRecognizer())
        self.assertIsNone(stt.push(b"\x00\x00" * 64))

    def test_begin_creates_recognizer(self) -> None:
        factory = _CountingFactory(FakeRecognizer(partial="hello"))
        stt = StreamingTranscriber(recognizer_factory=factory)
        self.assertEqual(factory.calls, 0)
        stt.begin()
        self.assertEqual(factory.calls, 1)

    def test_push_returns_partial(self) -> None:
        stt = StreamingTranscriber(
            recognizer_factory=lambda: FakeRecognizer(partial="hello world"),
            partial_interval_ms=0.0,
        )
        stt.begin()
        partial = stt.push(b"\x00\x00" * 64)
        self.assertEqual(partial, "hello world")

    def test_partial_text_reflects_ongoing_hypothesis(self) -> None:
        stt = StreamingTranscriber(
            recognizer_factory=lambda: FakeRecognizer(partial="open notepad"),
            partial_interval_ms=0.0,
        )
        stt.begin()
        stt.push(b"\x00\x00" * 64)
        self.assertEqual(stt.partial_text(), "open notepad")

    def test_partial_text_combines_segments_and_partial(self) -> None:
        stt = StreamingTranscriber(
            recognizer_factory=lambda: FakeRecognizer(
                partial="world",
                final_text="hello",
                final_confidence=0.9,
                force_final_on_chunk=1,
            ),
            partial_interval_ms=0.0,
        )
        stt.begin()
        stt.push(b"\x00\x00" * 64)  # triggers a mid-stream final "hello"
        stt.push(b"\x00\x00" * 64)  # partial "world"
        self.assertEqual(stt.partial_text(), "hello world")


class TestStreamingTranscriberFinals(unittest.TestCase):
    def test_finalize_accepts_high_confidence(self) -> None:
        stt = StreamingTranscriber(
            recognizer_factory=lambda: FakeRecognizer(
                final_text="open notepad", final_confidence=0.9
            )
        )
        stt.begin()
        result = stt.finalize()
        self.assertIsInstance(result, FinalTranscript)
        self.assertTrue(result.accepted)
        self.assertEqual(result.text, "open notepad")
        self.assertGreaterEqual(result.confidence, 0.9)
        self.assertEqual(result.rejected_reason, "")

    def test_finalize_rejects_low_confidence(self) -> None:
        stt = StreamingTranscriber(
            recognizer_factory=lambda: FakeRecognizer(
                final_text="random noise", final_confidence=0.2
            ),
            confidence_threshold=0.45,
        )
        stt.begin()
        result = stt.finalize()
        self.assertFalse(result.accepted)
        self.assertEqual(result.rejected_reason, "low confidence")

    def test_finalize_rejects_too_short(self) -> None:
        stt = StreamingTranscriber(
            recognizer_factory=lambda: FakeRecognizer(
                final_text="ok", final_confidence=0.9
            ),
            min_text_chars=4,
        )
        stt.begin()
        result = stt.finalize()
        self.assertFalse(result.accepted)
        self.assertEqual(result.rejected_reason, "too short")

    def test_finalize_without_begin_reports_not_started(self) -> None:
        stt = StreamingTranscriber(recognizer_factory=lambda: FakeRecognizer())
        result = stt.finalize()
        self.assertFalse(result.accepted)
        self.assertEqual(result.rejected_reason, "not started")

    def test_finalize_aggregates_midstream_segments(self) -> None:
        stt = StreamingTranscriber(
            recognizer_factory=lambda: FakeRecognizer(
                partial="world",
                final_text="hello",
                final_confidence=0.95,
                force_final_on_chunk=1,
            ),
            # Pass 1 only: this test exercises mid-stream segment aggregation,
            # not the multi-pass comparison.
            enable_multi_pass=False,
        )
        stt.begin()
        stt.push(b"\x00\x00" * 64)  # final "hello" (conf 0.95)
        result = stt.finalize()  # final "world"? FinalResult returns hello again
        # _consume_final_result captured "hello" mid-stream; finalize calls
        # FinalResult() once more (same scripted hello) -> duplicate text.
        self.assertTrue(result.accepted)
        self.assertIn("hello", result.text)


class TestStreamingTranscriberLifecycle(unittest.TestCase):
    def test_discard_stops_push(self) -> None:
        recognizer = FakeRecognizer(partial="x")
        stt = StreamingTranscriber(
            recognizer_factory=lambda: recognizer, partial_interval_ms=0.0
        )
        stt.begin()
        stt.discard()
        self.assertIsNone(stt.push(b"\x00\x00" * 64))

    def test_reset_creates_fresh_recognizer(self) -> None:
        factory = _CountingFactory(FakeRecognizer())
        stt = StreamingTranscriber(recognizer_factory=factory)
        stt.begin()
        stt.push(b"\x00\x00" * 64)
        stt.reset()
        self.assertEqual(factory.calls, 1)
        stt.begin()
        self.assertEqual(factory.calls, 2)

    def test_is_active_reflects_lifecycle(self) -> None:
        stt = StreamingTranscriber(recognizer_factory=lambda: FakeRecognizer())
        self.assertFalse(stt.is_active)
        stt.begin()
        self.assertTrue(stt.is_active)
        stt.finalize()
        self.assertFalse(stt.is_active)


class TestStreamingTranscriberConfidenceParsing(unittest.TestCase):
    def test_parse_confidence_prefers_top_level(self) -> None:
        data = {"text": "hi", "confidence": 0.8, "result": [{"conf": 0.1}]}
        self.assertEqual(StreamingTranscriber._parse_confidence(data), 0.8)

    def test_parse_confidence_averages_word_conf(self) -> None:
        data = {"text": "hi there", "result": [{"conf": 0.4}, {"conf": 0.6}]}
        self.assertEqual(StreamingTranscriber._parse_confidence(data), 0.5)

    def test_parse_confidence_penalizes_unk(self) -> None:
        self.assertEqual(
            StreamingTranscriber._parse_confidence({"text": "this [unk]"}),
            0.15,
        )

    def test_parse_confidence_unknown_when_no_data(self) -> None:
        # No top-level confidence and no per-word conf -> NO_CONFIDENCE
        # sentinel, so the gate can reject the untrusted transcript.
        self.assertLess(StreamingTranscriber._parse_confidence({"text": "hi there"}), 0.0)


class TestStreamingTranscriberHardenedGate(unittest.TestCase):
    """FIX-002: the confidence gate rejects low-quality transcripts."""

    def test_rejects_segment_with_no_confidence_data(self) -> None:
        stt = StreamingTranscriber(
            recognizer_factory=lambda: FakeRecognizer(
                final_text="hello there", include_confidence=False,
            )
        )
        stt.begin()
        result = stt.finalize()
        self.assertFalse(result.accepted)
        self.assertEqual(result.rejected_reason, "low confidence")

    def test_rejects_single_word_below_higher_bar(self) -> None:
        # "the" clears the base 0.5 threshold but not the 0.6 single-word bar.
        stt = StreamingTranscriber(
            recognizer_factory=lambda: FakeRecognizer(
                final_text="the", final_confidence=0.55,
            )
        )
        stt.begin()
        result = stt.finalize()
        self.assertFalse(result.accepted)
        self.assertEqual(result.rejected_reason, "low confidence")

    def test_accepts_single_word_with_high_confidence(self) -> None:
        stt = StreamingTranscriber(
            recognizer_factory=lambda: FakeRecognizer(
                final_text="chrome", final_confidence=0.9,
            )
        )
        stt.begin()
        result = stt.finalize()
        self.assertTrue(result.accepted)
        self.assertEqual(result.text, "chrome")

    def test_rejects_single_character_transcript(self) -> None:
        stt = StreamingTranscriber(
            recognizer_factory=lambda: FakeRecognizer(
                final_text="a", final_confidence=0.9,
            )
        )
        stt.begin()
        result = stt.finalize()
        self.assertFalse(result.accepted)
        self.assertEqual(result.rejected_reason, "too short")

    def test_rejects_multi_segment_with_weak_segment(self) -> None:
        # A 0.05-confidence segment must not hide inside the average.
        stt = StreamingTranscriber(
            recognizer_factory=lambda: FakeRecognizer(
                finals=[("open notepad", 0.95), ("garbage", 0.05)],
                force_final_on_chunk=(1, 2),
            ),
            enable_multi_pass=False,
        )
        stt.begin()
        stt.push(b"\x00\x00" * 64)
        stt.push(b"\x00\x00" * 64)
        result = stt.finalize()
        self.assertFalse(result.accepted)
        self.assertEqual(result.rejected_reason, "low confidence")

    def test_accepts_multi_segment_with_strong_segments(self) -> None:
        stt = StreamingTranscriber(
            recognizer_factory=lambda: FakeRecognizer(
                finals=[("open notepad", 0.9), ("and chrome", 0.85)],
                force_final_on_chunk=(1, 2),
            ),
            enable_multi_pass=False,
        )
        stt.begin()
        stt.push(b"\x00\x00" * 64)
        stt.push(b"\x00\x00" * 64)
        result = stt.finalize()
        self.assertTrue(result.accepted)
        self.assertEqual(result.text, "open notepad and chrome")


class TestStreamingTranscriberHealth(unittest.TestCase):
    """FIX-002: repeated recognizer failures are contained and recovered."""

    def test_recognizer_dropped_after_repeated_failures(self) -> None:
        factory = _CountingFactory(FakeRecognizer(raise_on_accept=True))
        stt = StreamingTranscriber(recognizer_factory=factory)
        stt.begin()
        for _ in range(MAX_CONSECUTIVE_ERRORS):
            self.assertIsNone(stt.push(b"\x00\x00" * 64))
        self.assertTrue(stt._broken)
        self.assertIsNone(stt._recognizer)
        self.assertFalse(stt.is_active)

    def test_finalize_reports_recognizer_error_when_broken(self) -> None:
        stt = StreamingTranscriber(
            recognizer_factory=lambda: FakeRecognizer(raise_on_accept=True)
        )
        stt.begin()
        for _ in range(MAX_CONSECUTIVE_ERRORS):
            stt.push(b"\x00\x00" * 64)
        result = stt.finalize()
        self.assertFalse(result.accepted)
        self.assertEqual(result.rejected_reason, "recognizer error")

    def test_next_capture_recreates_recognizer(self) -> None:
        factory = _CountingFactory(FakeRecognizer(raise_on_accept=True))
        stt = StreamingTranscriber(recognizer_factory=factory)
        stt.begin()
        for _ in range(MAX_CONSECUTIVE_ERRORS):
            stt.push(b"\x00\x00" * 64)
        stt.begin()  # fresh capture -> fresh recognizer
        self.assertEqual(factory.calls, 2)
        self.assertFalse(stt._broken)

    def test_single_transient_error_does_not_drop_recognizer(self) -> None:
        recognizer = FakeRecognizer(final_text="open notepad", final_confidence=0.9)

        def flaky(chunk: bytes) -> bool:  # noqa: ARG001
            if recognizer.accepted_waveforms == 0:
                raise RuntimeError("transient")
            recognizer.accepted_waveforms += 1
            return False

        recognizer.AcceptWaveform = flaky  # type: ignore[method-assign]
        stt = StreamingTranscriber(recognizer_factory=lambda: recognizer)
        stt.begin()
        stt.push(b"\x00\x00" * 64)  # fails once
        self.assertFalse(stt._broken)
        self.assertIsNotNone(stt._recognizer)


class TestStreamingTranscriberMultiPass(unittest.TestCase):
    """FIX-002: Pass 2 re-decodes the buffered utterance and the higher-
    confidence transcript wins (requirement: multi-pass recognition)."""

    @staticmethod
    def _pushed(recorder: FakeRecognizer) -> StreamingTranscriber:
        stt = StreamingTranscriber(recognizer_factory=recorder)
        stt.begin()
        stt.push(b"\x00\x00" * 64)
        stt.push(b"\x00\x00" * 64)
        return stt

    def test_pass2_higher_confidence_wins(self) -> None:
        factory = _TwoPassFactory(
            FakeRecognizer(final_text="open graf", final_confidence=0.5),
            FakeRecognizer(final_text="open graph", final_confidence=0.95),
        )
        stt = self._pushed(factory)
        result = stt.finalize()
        self.assertTrue(result.accepted)
        self.assertEqual(result.text, "open graph")
        self.assertEqual(result.pass_used, "pass2")
        self.assertEqual(factory.calls, 2)

    def test_pass2_recovers_when_pass1_empty(self) -> None:
        factory = _TwoPassFactory(
            FakeRecognizer(final_text="", final_confidence=0.0),
            FakeRecognizer(final_text="open notepad", final_confidence=0.9),
        )
        stt = self._pushed(factory)
        result = stt.finalize()
        self.assertTrue(result.accepted)
        self.assertEqual(result.text, "open notepad")
        self.assertEqual(result.pass_used, "pass2")

    def test_pass1_wins_when_more_confident(self) -> None:
        factory = _TwoPassFactory(
            FakeRecognizer(final_text="open notepad", final_confidence=0.9),
            FakeRecognizer(final_text="open notepad", final_confidence=0.7),
        )
        stt = self._pushed(factory)
        result = stt.finalize()
        self.assertTrue(result.accepted)
        self.assertEqual(result.text, "open notepad")
        self.assertEqual(result.pass_used, "pass1")

    def test_pass2_low_confidence_cannot_hijack_accepted_pass1(self) -> None:
        factory = _TwoPassFactory(
            FakeRecognizer(final_text="open notepad", final_confidence=0.9),
            FakeRecognizer(final_text="garbage", final_confidence=0.2),
        )
        stt = self._pushed(factory)
        result = stt.finalize()
        self.assertTrue(result.accepted)
        self.assertEqual(result.text, "open notepad")
        self.assertEqual(result.pass_used, "pass1")

    def test_pass2_hallucination_never_executed(self) -> None:
        # Pass 1 is clean; Pass 2 invents a low-confidence word — must not win.
        factory = _TwoPassFactory(
            FakeRecognizer(final_text="open notepad", final_confidence=0.9),
            FakeRecognizer(final_text="open graf", final_confidence=0.4),
        )
        stt = self._pushed(factory)
        result = stt.finalize()
        self.assertTrue(result.accepted)
        self.assertEqual(result.text, "open notepad")

    def test_disabled_multi_pass_uses_pass1_only(self) -> None:
        factory = _TwoPassFactory(
            FakeRecognizer(final_text="open notepad", final_confidence=0.9),
            FakeRecognizer(final_text="open chrome", final_confidence=0.99),
        )
        stt = StreamingTranscriber(
            recognizer_factory=factory, enable_multi_pass=False,
        )
        stt.begin()
        stt.push(b"\x00\x00" * 64)
        result = stt.finalize()
        self.assertEqual(factory.calls, 1)
        self.assertEqual(result.text, "open notepad")
        self.assertEqual(result.pass_used, "pass1")

    def test_second_pass_exception_falls_back_to_pass1(self) -> None:
        good = FakeRecognizer(final_text="open notepad", final_confidence=0.9)
        broken = FakeRecognizer(raise_on_accept=True)
        factory = _TwoPassFactory(good, broken)
        stt = self._pushed(factory)
        result = stt.finalize()
        self.assertTrue(result.accepted)
        self.assertEqual(result.text, "open notepad")
        self.assertEqual(result.pass_used, "pass1")


class TestPreloadModel(unittest.TestCase):
    """FIX-002: the model preload never raises and reports availability."""

    def test_preload_success(self) -> None:
        with unittest.mock.patch(
            "voice.streaming_stt._get_shared_model", return_value=object()
        ):
            self.assertTrue(preload_model(wait=True))

    def test_preload_failure_returns_false(self) -> None:
        with unittest.mock.patch(
            "voice.streaming_stt._get_shared_model",
            side_effect=RuntimeError("vosk unavailable"),
        ):
            self.assertFalse(preload_model(wait=True))


if __name__ == "__main__":
    unittest.main()
