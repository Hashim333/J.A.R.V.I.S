"""
voice/streaming_stt.py

Streaming, partial-transcript speech recognition built on Vosk.

Why streaming (vs the old record-then-send-one-shot flow):

  * partial transcripts are produced as the user speaks, so the UI can
    show live text and nothing is ever lost mid-sentence,
  * a *brief pause* does not end the utterance — segments finalize only
    when the caller asks (VAD hangover or a hard deadline),
  * the final transcript is accepted **only if its confidence clears a
    threshold**, otherwise it is reported as rejected so the pipeline can
    keep listening instead of acting on a hallucination,
  * transcripts with **no confidence data at all**, containing ``[unk]``,
    or too short to be a real command are rejected rather than executed,
  * concatenated mid-stream segments must satisfy a **stricter bar** and a
    floor on every individual segment, so two separate utterances are never
    silently merged into one command,
  * **multi-pass recognition**: the full utterance is buffered and, on
    finalize, re-decoded by a *fresh* recognizer (Pass 2 — a clean, whole-
    utterance decode, optionally a higher-accuracy model).  When the two
    passes disagree, their confidences are compared and the best transcript
    wins; a phantom can therefore be rescued or a hallucination discarded,
  * the recognizer self-heals: repeated ``AcceptWaveform`` failures drop
    the broken recognizer and a fresh one is created on the next capture.

The recognizer factory can be injected for headless tests; by default the
shared Vosk model is used (see :func:`preload_model` to warm it at startup).
"""
from __future__ import annotations

import json
import logging
import os
import threading
import time
from typing import Any, Callable

logger = logging.getLogger(__name__)

# Default minimum final confidence for acceptance.
DEFAULT_CONFIDENCE_THRESHOLD = 0.5

# ``_parse_confidence`` returns this sentinel when a segment carries no
# confidence information at all (no top-level confidence and no per-word
# ``conf``).  Such a segment is untrustworthy and causes rejection.
NO_CONFIDENCE = -1.0

# A recognizer reporting this many consecutive AcceptWaveform failures is
# considered broken and is dropped so a fresh one is created next capture.
MAX_CONSECUTIVE_ERRORS = 5


class FinalTranscript:
    """A finalized speech segment with an acceptance decision."""

    __slots__ = (
        "text", "confidence", "accepted", "duration_ms",
        "rejected_reason", "pass_used",
    )

    def __init__(
        self,
        text: str,
        confidence: float,
        accepted: bool,
        duration_ms: float = 0.0,
        rejected_reason: str = "",
        pass_used: str = "pass1",
    ) -> None:
        self.text = text
        self.confidence = confidence
        self.accepted = accepted
        self.duration_ms = duration_ms
        self.rejected_reason = rejected_reason
        self.pass_used = pass_used

    @property
    def is_empty(self) -> bool:
        return not self.text or not self.text.strip()

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return (
            f"FinalTranscript(text={self.text!r}, confidence={self.confidence:.3f}, "
            f"accepted={self.accepted})"
        )


_shared_model: Any = None
_model_lock = threading.Lock()


def _get_shared_model():
    """Load the shared Vosk model once (thread-safe).

    The model language is configurable via ``JARVIS_VOSK_LANG`` (default
    ``en-us``) so accent-optimised / non-English models can be selected
    without code changes.
    """
    global _shared_model
    if _shared_model is None:
        with _model_lock:
            if _shared_model is None:
                import vosk

                lang = os.environ.get("JARVIS_VOSK_LANG", "en-us")
                _shared_model = vosk.Model(lang=lang)
    return _shared_model


def preload_model(wait: bool = False) -> bool:
    """Warm the shared Vosk model so the first capture never stalls.

    The one-time model download/load can take seconds; by default it runs on
    a daemon thread so application startup is not blocked.  Captures that
    start before the load finishes will simply wait on the internal model
    lock (the preload is almost always complete by the time a user speaks).

    Args:
        wait: When True, block until the model is loaded (or fails).

    Returns:
        True when the model is available (or the preload was scheduled),
        False when the model could not be loaded.  Never raises.
    """
    outcome: list[bool] = []

    def _load() -> None:
        try:
            model = _get_shared_model()
            logger.info(
                "Vosk model preloaded (%s)", getattr(model, "name", "shared")
            )
            outcome.append(True)
        except Exception as exc:  # noqa: BLE001
            logger.error("Vosk model preload failed: %s", exc, exc_info=True)
            outcome.append(False)

    thread = threading.Thread(target=_load, name="vosk-preload", daemon=True)
    thread.start()
    if wait:
        thread.join(timeout=120.0)
        return bool(outcome and outcome[0])
    return True


class StreamingTranscriber:
    """
    Streaming transcriber with partial updates and confidence-gated finals.

    Args:
        sample_rate: 16 kHz mono 16-bit pipeline audio.
        recognizer_factory: Callable that returns a Vosk-compatible object
            exposing ``AcceptWaveform(bytes) -> bool``,
            ``PartialResult() -> str`` and ``FinalResult() -> str``.  Injected
            in headless tests.
        confidence_threshold: Minimum final confidence for ``accepted=True``.
        default_confidence: Fallback confidence used only when a segment list
            is otherwise empty (should rarely matter — segments normally carry
            real confidence).
        min_text_chars: Ignore finals shorter than this many characters.
        min_text_words: Ignore finals with fewer than this many words.
        single_word_min_confidence: A one-word transcript (the classic
            hallucination shape) must clear this higher bar to be accepted.
        multi_segment_min_confidence: When several mid-stream finals are
            concatenated, the combined confidence must clear this stricter bar.
        segment_floor: In a multi-segment result, every individual segment
            must be at least this confident, so one weak segment cannot hide
            inside an average.
        enable_multi_pass: Re-decode the buffered utterance on finalize with a
            fresh recognizer and pick the higher-confidence transcript.
        second_pass_factory: Optional recognizer factory for Pass 2 (e.g. a
            higher-accuracy model).  Defaults to the primary factory / model.
        partial_interval_ms: Throttle partial transcript callbacks.
    """

    def __init__(
        self,
        sample_rate: int = 16000,
        recognizer_factory: Callable[[], Any] | None = None,
        confidence_threshold: float = DEFAULT_CONFIDENCE_THRESHOLD,
        default_confidence: float = 0.5,
        min_text_chars: int = 2,
        min_text_words: int = 1,
        single_word_min_confidence: float = 0.6,
        multi_segment_min_confidence: float = 0.6,
        segment_floor: float = 0.3,
        enable_multi_pass: bool = True,
        second_pass_factory: Callable[[], Any] | None = None,
        partial_interval_ms: float = 350.0,
    ) -> None:
        self._sample_rate = sample_rate
        self._recognizer_factory = recognizer_factory
        self._confidence_threshold = float(confidence_threshold)
        self._default_confidence = float(default_confidence)
        self._min_text_chars = int(min_text_chars)
        self._min_text_words = int(min_text_words)
        self._single_word_min_confidence = float(single_word_min_confidence)
        self._multi_segment_min_confidence = float(multi_segment_min_confidence)
        self._segment_floor = float(segment_floor)
        self._enable_multi_pass = bool(enable_multi_pass)
        self._second_pass_factory = second_pass_factory
        self._partial_interval_ms = float(partial_interval_ms)

        self._recognizer: Any = None
        self._lock = threading.Lock()
        self._reset_state()

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def _reset_state(self) -> None:
        self._segments: list[tuple[str, float]] = []  # finalized segment (text, conf)
        self._partial = ""
        self._last_partial_at = 0.0
        self._started_at: float | None = None
        self._sample_count = 0
        self._finished = False
        self._consecutive_errors = 0
        self._broken = False
        self._pcm_buffer = bytearray()

    def begin(self) -> None:
        """Start a fresh transcription session."""
        with self._lock:
            self._reset_state()
            if self._recognizer is None:
                if self._recognizer_factory is not None:
                    self._recognizer = self._recognizer_factory()
                else:
                    self._recognizer = self._make_default_recognizer()
            self._started_at = time.monotonic()

    def _make_default_recognizer(self) -> Any:
        import vosk

        model = _get_shared_model()
        return vosk.KaldiRecognizer(model, self._sample_rate)

    def _run_second_pass(self) -> tuple[str, float] | None:
        """Re-decode the buffered utterance with a fresh recognizer.

        Pass 2 is a clean whole-utterance decode (no partial/segment state),
        optionally from a higher-accuracy recognizer supplied via
        ``second_pass_factory``.  Returns ``(text, confidence)`` or None on
        failure/empty — never raises.
        """
        buffer = bytes(self._pcm_buffer)
        if not buffer:
            return None
        try:
            if self._second_pass_factory is not None:
                rec = self._second_pass_factory()
            elif self._recognizer_factory is not None:
                rec = self._recognizer_factory()
            else:
                rec = self._make_default_recognizer()
            begin = getattr(rec, "begin", None)
            if callable(begin):
                begin()
            for i in range(0, len(buffer), 8192):
                rec.AcceptWaveform(buffer[i : i + 8192])
            raw = rec.FinalResult()
        except Exception as exc:
            logger.error("Streaming STT second pass failed: %s", exc, exc_info=True)
            return None
        try:
            data = json.loads(raw)
        except (TypeError, ValueError):
            return None
        text = str(data.get("text", "") or "").strip()
        if not text:
            return None
        return (text, self._parse_confidence(data))

    def push(self, pcm_chunk: bytes) -> str | None:
        """Feed a 16-bit PCM chunk; returns a (throttled) partial transcript.

        Returns the latest partial text (or None when nothing has been
        transcribed yet / outside the throttle window).

        A recognizer that fails repeatedly is dropped and marked broken; a
        fresh one is created on the next :meth:`begin`.
        """
        if not pcm_chunk:
            return None
        with self._lock:
            if self._recognizer is None or self._finished:
                return None
            self._sample_count += len(pcm_chunk) // 2
            self._pcm_buffer += pcm_chunk
            try:
                is_final = self._recognizer.AcceptWaveform(pcm_chunk)
            except Exception as exc:
                self._consecutive_errors += 1
                logger.error(
                    "Streaming STT AcceptWaveform failed (error %d): %s",
                    self._consecutive_errors, exc, exc_info=True,
                )
                if self._consecutive_errors >= MAX_CONSECUTIVE_ERRORS:
                    logger.error(
                        "Streaming STT: %d consecutive errors — dropping "
                        "recognizer; a fresh one will be created on the "
                        "next capture",
                        self._consecutive_errors,
                    )
                    self._recognizer = None
                    self._broken = True
                return None
            self._consecutive_errors = 0

            if is_final:
                self._consume_final_result()

            now = time.monotonic()
            if (now - self._last_partial_at) * 1000.0 < self._partial_interval_ms:
                return None
            try:
                raw = self._recognizer.PartialResult()
            except Exception:
                return None
            try:
                data = json.loads(raw)
                self._partial = str(data.get("partial", "") or "").strip()
            except (TypeError, ValueError):
                return None
            self._last_partial_at = now
            return self._partial or None

    def _consume_final_result(self) -> None:
        try:
            raw = self._recognizer.FinalResult()
        except Exception as exc:
            self._consecutive_errors += 1
            logger.error(
                "Streaming STT FinalResult failed (error %d): %s",
                self._consecutive_errors, exc, exc_info=True,
            )
            return
        try:
            data = json.loads(raw)
        except (TypeError, ValueError):
            return
        text = str(data.get("text", "") or "").strip()
        if text:
            self._segments.append((text, self._parse_confidence(data)))

    def partial_text(self) -> str:
        """Current live partial hypothesis (whole utterance so far)."""
        with self._lock:
            base = " ".join(text for text, _ in self._segments)
            if self._partial:
                return (base + " " + self._partial).strip() if base else self._partial
            return base

    def finalize(self) -> FinalTranscript:
        """End the session and produce a confidence-gated final transcript.

        Pass 1 is the live streaming decode (partials + segments).  When
        multi-pass is enabled, the buffered utterance is re-decoded by a
        fresh recognizer (Pass 2) and the higher-confidence transcript wins.
        """
        with self._lock:
            if self._recognizer is None:
                if self._broken or self._started_at is not None:
                    # Either the recognizer was dropped after repeated
                    # failures, or it could never be created (model load /
                    # download failed) — surface a clear reason instead of
                    # the misleading "not started".
                    return FinalTranscript("", 0.0, False, 0.0, "recognizer error")
                return FinalTranscript("", 0.0, False, 0.0, "not started")
            try:
                raw = self._recognizer.FinalResult()
            except Exception:
                raw = "{}"
            try:
                data = json.loads(raw)
            except (TypeError, ValueError):
                data = {}

            text = str(data.get("text", "") or "").strip()
            if text:
                self._segments.append((text, self._parse_confidence(data)))

            duration_ms = 0.0
            if self._started_at is not None:
                duration_ms = (time.monotonic() - self._started_at) * 1000.0

            self._finished = True
            pass1 = self._build_result(duration_ms)
            result = pass1

            if self._enable_multi_pass:
                pass2 = self._run_second_pass()
                if pass2 is not None and pass2[0]:
                    second = self._build_result(
                        duration_ms, text=pass2[0], confidence=pass2[1],
                        pass_used="pass2",
                    )
                    if second.accepted and not pass1.accepted:
                        result = second
                    elif second.confidence > pass1.confidence:
                        result = second
                    elif second.confidence == pass1.confidence and second.text != pass1.text:
                        result = second
                    logger.info(
                        "MULTI-PASS — pass1=%r (%.3f, accepted=%s) "
                        "pass2=%r (%.3f, accepted=%s) winner=%s",
                        pass1.text, pass1.confidence, pass1.accepted,
                        second.text, second.confidence, second.accepted,
                        result.pass_used,
                    )
            return result

    def _build_result(
        self,
        duration_ms: float,
        text: str | None = None,
        confidence: float | None = None,
        pass_used: str = "pass1",
    ) -> FinalTranscript:
        if text is not None:
            # Whole-utterance transcript (Pass 2 override): gate a single
            # clean decode instead of re-running segment aggregation.
            text = " ".join(text.split())
            confidence = float(confidence)
            reason = ""
            if not text:
                reason = "no speech recognized"
            elif len(text) < self._min_text_chars:
                reason = "too short"
            elif len(text.split()) < self._min_text_words:
                reason = f"too short ({len(text.split())} word(s))"
            elif len(text.split()) == 1 and confidence < self._single_word_min_confidence:
                reason = "low confidence"
            elif confidence < self._confidence_threshold:
                reason = "low confidence"
            return FinalTranscript(
                text=text,
                confidence=confidence,
                accepted=(not reason),
                duration_ms=duration_ms,
                rejected_reason=reason,
                pass_used=pass_used,
            )

        if not self._segments:
            return FinalTranscript("", 0.0, False, duration_ms, "no speech recognized")

        texts = [text for text, _ in self._segments]
        text = " ".join(texts).strip()
        confidences = [conf for _, conf in self._segments]

        # Any segment without confidence data at all is untrustworthy —
        # reject instead of guessing (Vosk normally reports per-word conf).
        if any(conf < 0.0 for conf in confidences):
            known = [conf for conf in confidences if conf >= 0.0]
            confidence = min(known) if known else 0.0
            reason = "low confidence"
        else:
            confidence = sum(confidences) / len(confidences) if confidences else self._default_confidence
            reason = ""

        if len(text) < self._min_text_chars:
            reason = "too short"
        elif len(text.split()) < self._min_text_words:
            reason = f"too short ({len(text.split())} word(s))"
        else:
            word_count = len(text.split())
            min_confidence = self._confidence_threshold
            if len(self._segments) > 1:
                # Concatenated finals can merge separate utterances: require a
                # stricter bar and a floor on every individual segment.
                min_confidence = max(min_confidence, self._multi_segment_min_confidence)
                if min(confidences) < self._segment_floor:
                    reason = "low confidence"
            if not reason:
                if word_count == 1 and confidence < self._single_word_min_confidence:
                    reason = "low confidence"
                elif confidence < min_confidence:
                    reason = "low confidence"

        return FinalTranscript(
            text=text,
            confidence=confidence,
            accepted=(not reason),
            duration_ms=duration_ms,
            rejected_reason=reason,
            pass_used=pass_used,
        )

    @staticmethod
    def _parse_confidence(data: dict) -> float:
        """Extract a confidence score from a Vosk result dict.

        Prefers the top-level ``confidence``, then the average of per-word
        ``conf`` values, then a text-based heuristic penalizing ``[unk]``.

        Returns :data:`NO_CONFIDENCE` (-1.0) when the result carries no
        confidence information at all, so the caller can reject the segment
        instead of trusting an unmeasured transcript.
        """
        try:
            conf = data.get("confidence")
            if conf is not None:
                conf = float(conf)
                if 0.0 <= conf <= 1.0:
                    return conf
        except (TypeError, ValueError):
            pass

        result = data.get("result")
        if isinstance(result, list) and result:
            confs = []
            for word in result:
                try:
                    c = float(word.get("conf", 0.0))
                except (TypeError, ValueError):
                    c = 0.0
                if 0.0 <= c <= 1.0:
                    confs.append(c)
            if confs:
                return sum(confs) / len(confs)

        text = str(data.get("text", "") or "").strip()
        if not text:
            return 0.0
        if "[unk]" in text.casefold():
            return 0.15
        return NO_CONFIDENCE

    # ------------------------------------------------------------------
    # Utilities
    # ------------------------------------------------------------------

    @property
    def is_active(self) -> bool:
        return self._recognizer is not None and not self._finished

    @property
    def duration_ms(self) -> float:
        if self._started_at is None:
            return 0.0
        return (time.monotonic() - self._started_at) * 1000.0

    def discard(self) -> None:
        """Abandon the current session without producing a result."""
        with self._lock:
            self._finished = True

    def reset(self) -> None:
        """Drop the recognizer so a fresh one is created on next begin()."""
        with self._lock:
            self._recognizer = None
            self._reset_state()
