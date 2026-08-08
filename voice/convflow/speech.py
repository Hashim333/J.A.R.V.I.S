"""
voice/pipeline/speech.py

``SpeechRecognizer`` — confidence-gated, streaming ASR for Conversation Mode.

Wraps the existing :class:`voice.streaming_stt.StreamingTranscriber` and
enforces the redesign's stricter acceptance gate:

    * minimum final confidence **0.85**,
    * reject empty text,
    * reject one-word / garbage transcripts (a real command is rarely a
      single hallucinated word).

The result is reported as ``(text, confidence, accepted, reason)`` so the
orchestrator can either route it to the LLM (accepted) or ask the user to
repeat (rejected) instead of acting on a phantom.
"""
from __future__ import annotations

import logging
from typing import Callable

from voice.streaming_stt import StreamingTranscriber

logger = logging.getLogger(__name__)

DEFAULT_MIN_CONFIDENCE = 0.85


class SpeechResult:
    __slots__ = ("text", "confidence", "accepted", "reason")

    def __init__(
        self, text: str, confidence: float, accepted: bool, reason: str = ""
    ) -> None:
        self.text = text
        self.confidence = confidence
        self.accepted = accepted
        self.reason = reason

    @property
    def is_empty(self) -> bool:
        return not self.text or not self.text.strip()

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return (
            f"SpeechResult(text={self.text!r}, confidence={self.confidence:.3f}, "
            f"accepted={self.accepted}, reason={self.reason!r})"
        )


class SpeechRecognizer:
    """Confidence-gated streaming recognizer.

    Args:
        min_confidence: Final confidence required for acceptance.
        min_text_words: Minimum word count to reject one-word garbage.
        sample_rate: Pipeline rate (16 kHz).
        transcriber_factory: Returns a ``StreamingTranscriber``.  Injected for
            headless tests so the heavy Vosk model is not required.
    """

    def __init__(
        self,
        min_confidence: float = DEFAULT_MIN_CONFIDENCE,
        min_text_words: int = 1,
        sample_rate: int = 16000,
        transcriber_factory=None,
    ) -> None:
        self._min_confidence = float(min_confidence)
        self._min_text_words = int(min_text_words)
        self._sample_rate = sample_rate
        self._transcriber = (
            transcriber_factory
            if callable(transcriber_factory)
            else lambda: StreamingTranscriber(
                sample_rate=sample_rate,
                confidence_threshold=self._min_confidence,
                min_text_chars=1,
            )
        )
        self._current = None

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def begin(self) -> None:
        self._current = self._transcriber()
        self._current.begin()

    def push(self, chunk: bytes) -> str | None:
        if self._current is None:
            return None
        return self._current.push(chunk)

    def partial_text(self) -> str:
        if self._current is None:
            return ""
        return self._current.partial_text()

    def finalize(self) -> SpeechResult:
        if self._current is None:
            return SpeechResult("", 0.0, False, "not started")
        final = self._current.finalize()
        return self._gate(final.text, final.confidence, final.duration_ms)

    def discard(self) -> None:
        if self._current is not None:
            try:
                self._current.discard()
            except Exception:
                pass
        self._current = None

    # ------------------------------------------------------------------
    # Gate
    # ------------------------------------------------------------------

    def _gate(self, text: str, confidence: float, duration_ms: float) -> SpeechResult:
        text = (text or "").strip()
        # Optional non-numeric check away from the VAD path.
        if not text:
            return SpeechResult("", 0.0, False, "no speech recognized")
        if len(text.split()) < self._min_text_words:
            return SpeechResult(
                text, confidence, False,
                f"too short ({len(text.split())} word(s))",
            )
        if confidence < self._min_confidence:
            return SpeechResult(
                text, confidence, False,
                f"low confidence ({confidence:.3f})",
            )
        return SpeechResult(text, confidence, True, "")

    @property
    def is_active(self) -> bool:
        return self._current is not None and getattr(self._current, "is_active", False)