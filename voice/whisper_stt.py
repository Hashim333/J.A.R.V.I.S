"""
voice/whisper_stt.py

Faster-Whisper (CTranslate2) transcription — replaces the Vosk streaming
transcriber as the capture STT engine.

Design notes:

  * The capture VAD already finds the utterance boundaries, so this
    transcriber is **batch-oriented**: PCM is buffered during the capture
    and the whole utterance is decoded once on ``finalize``.  A single
    clean Whisper decode beats a Vosk-style streaming decode for accuracy,
    and there is no lightweight Whisper streaming path to maintain.
  * Live partials are best-effort.  A background daemon thread re-decodes
    the buffer on a throttle so the UI still shows text as the user speaks,
    without ever blocking the microphone thread.
  * The CTranslate2 model is loaded once and shared (thread-safe).  It is
    pinned to CPU with ``compute_type="int8"`` so it fits low-end hardware.
  * Indian-English / command tuning: the language is pinned to English,
    decoding is greedy (``beam_size=1``, ``temperature=0``) for speed, the
    built-in Silero VAD filter removes non-speech, and an accent-aware
    ``initial_prompt`` biases the decoder toward command phrasing.
  * Confidence is the duration-weighted mean of ``exp(avg_logprob)`` per
    segment, scaled by ``1 - no_speech_prob`` (a segment with no real
    speech collapses toward zero).  The same gate rules as the Vosk
    transcriber decide acceptance: threshold, a stricter bar for single
    words, too-short, and no-speech rejection.

The public API mirrors ``voice.streaming_stt.StreamingTranscriber``
(``begin`` / ``push`` / ``partial_text`` / ``finalize`` / ``discard`` /
``reset`` / ``is_active`` / ``duration_ms``) so the duplex session can swap
engines without changing its call sites.  ``FinalTranscript`` is reused
from ``streaming_stt`` so both engines share one result type.
"""
from __future__ import annotations

import logging
import math
import os
import threading
import time
from typing import Any, Callable

from voice.streaming_stt import FinalTranscript

logger = logging.getLogger(__name__)

# Default minimum final confidence for acceptance (matches the Vosk gate).
DEFAULT_CONFIDENCE_THRESHOLD = 0.5

# Whisper is strong at English; the accent-aware prompt only nudges the
# decoder toward short command phrasing (it must never read back the prompt).
_INITIAL_PROMPT = (
    "The following are short spoken commands in Indian-accented English: "
    "open chrome, play music, increase volume, shut down the computer, "
    "search for the weather, pause, next, what time is it, open settings."
)

# Max buffer length (seconds) that the background partial decoder will
# re-decode — longer captures are left to the authoritative ``finalize``.
_MAX_PARTIAL_SECONDS = 20.0


def _model_size() -> str:
    return os.getenv("JARVIS_WHISPER_MODEL", "base")


def _model_language() -> str | None:
    lang = os.getenv("JARVIS_WHISPER_LANG", "en").strip()
    return lang or None


def _cpu_threads() -> int:
    try:
        return int(os.getenv("JARVIS_WHISPER_THREADS", "0"))
    except (TypeError, ValueError):
        return 0


_shared_model: Any = None
_model_lock = threading.Lock()


def _get_shared_model():
    """Load the shared Faster-Whisper model once (thread-safe).

    Configurable via ``JARVIS_WHISPER_MODEL`` (default ``base``),
    ``JARVIS_WHISPER_LANG`` (default ``en``) and ``JARVIS_WHISPER_THREADS``.
    """
    global _shared_model
    if _shared_model is None:
        with _model_lock:
            if _shared_model is None:
                from faster_whisper import WhisperModel

                _shared_model = WhisperModel(
                    _model_size(),
                    device="cpu",
                    compute_type="int8",
                    cpu_threads=_cpu_threads(),
                )
    return _shared_model


def preload_model(wait: bool = False) -> bool:
    """Warm the shared Whisper model so the first capture never stalls.

    The one-time model download/load can take tens of seconds; by default it
    runs on a daemon thread so application startup is not blocked.  Captures
    that start before the load finishes simply wait on the internal model
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
            logger.info("Whisper model preloaded (%s)", getattr(model, "model", "shared"))
            outcome.append(True)
        except Exception as exc:  # noqa: BLE001
            logger.error("Whisper model preload failed: %s", exc, exc_info=True)
            outcome.append(False)

    thread = threading.Thread(target=_load, name="whisper-preload", daemon=True)
    thread.start()
    if wait:
        thread.join(timeout=600.0)
        return bool(outcome and outcome[0])
    return True


class WhisperRecognizer:
    """
    Batch Whisper transcriber with best-effort partials and confidence-gated
    finals.

    Args:
        sample_rate: 16 kHz mono 16-bit pipeline audio.
        model_factory: Callable returning the object used for decoding.  It
            must expose ``transcribe(audio, **kwargs)`` returning a
            ``(segments, info)`` tuple (injected in headless tests).
        language: Whisper source language (pinned to English by default).
        confidence_threshold: Minimum final confidence for ``accepted=True``.
        min_text_chars / min_text_words: Ignore finals shorter than this.
        single_word_min_confidence: A one-word transcript (the classic
            hallucination shape) must clear this higher bar.
        enable_partials: Run the background partial decoder.
        partial_interval_ms: Throttle for partial callbacks / decodes.
        vad_filter: Let the built-in Silero VAD drop non-speech in transcribe.
    """

    def __init__(
        self,
        sample_rate: int = 16000,
        model_factory: Callable[[], Any] | None = None,
        language: str | None = None,
        confidence_threshold: float = DEFAULT_CONFIDENCE_THRESHOLD,
        min_text_chars: int = 2,
        min_text_words: int = 1,
        single_word_min_confidence: float = 0.6,
        enable_partials: bool = True,
        partial_interval_ms: float = 1200.0,
        vad_filter: bool = True,
    ) -> None:
        self._sample_rate = sample_rate
        self._model_factory = model_factory
        self._language = language or _model_language()
        self._confidence_threshold = float(confidence_threshold)
        self._min_text_chars = int(min_text_chars)
        self._min_text_words = int(min_text_words)
        self._single_word_min_confidence = float(single_word_min_confidence)
        self._enable_partials = bool(enable_partials)
        self._partial_interval_ms = float(partial_interval_ms)
        self._vad_filter = bool(vad_filter)

        self._model: Any = None
        self._lock = threading.Lock()
        # Serialises decoder use between the partial worker and finalize
        # (CTranslate2 is not safe for concurrent transcribe calls).
        self._decode_lock = threading.Lock()
        self._partial_worker: threading.Thread | None = None
        self._reset_state()

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def _reset_state(self) -> None:
        self._pcm_buffer = bytearray()
        self._partial = ""
        self._last_partial_at = 0.0
        self._started_at: float | None = None
        self._sample_count = 0
        self._finished = False

    def _ensure_model(self) -> Any:
        if self._model is None:
            if self._model_factory is not None:
                self._model = self._model_factory()
            else:
                self._model = _get_shared_model()
        return self._model

    def begin(self) -> None:
        """Start a fresh transcription session."""
        with self._lock:
            self._reset_state()
            self._started_at = time.monotonic()

    def push(self, pcm_chunk: bytes) -> str | None:
        """Buffer a 16-bit PCM chunk; return a throttled partial when one
        has been produced by the background decoder."""
        if not pcm_chunk:
            return None
        with self._lock:
            if self._finished:
                return None
            self._sample_count += len(pcm_chunk) // 2
            self._pcm_buffer += pcm_chunk
            should_emit = (
                bool(self._partial)
                and (time.monotonic() - self._last_partial_at) * 1000.0
                >= self._partial_interval_ms
            )
            if should_emit:
                self._last_partial_at = time.monotonic()
                text = self._partial
            else:
                text = None
        if self._enable_partials:
            self._start_partial_worker()
        return text

    def partial_text(self) -> str:
        """Current live partial hypothesis (whole utterance so far)."""
        with self._lock:
            return self._partial

    # ------------------------------------------------------------------
    # Background partial decoding
    # ------------------------------------------------------------------

    def _start_partial_worker(self) -> None:
        with self._lock:
            if self._partial_worker is not None and self._partial_worker.is_alive():
                return
            if self._finished:
                return
            self._partial_worker = threading.Thread(
                target=self._partial_loop,
                name="whisper-partial",
                daemon=True,
            )
            self._partial_worker.start()

    def _partial_loop(self) -> None:
        interval = max(0.1, self._partial_interval_ms / 1000.0)
        while True:
            time.sleep(interval)
            with self._lock:
                if self._finished:
                    return
                buffer = bytes(self._pcm_buffer)
            if not buffer or len(buffer) // 2 > _MAX_PARTIAL_SECONDS * self._sample_rate:
                continue
            try:
                text, _conf = self._transcribe_buffer(buffer)
            except Exception as exc:
                logger.debug("Partial decode skipped: %s", exc)
                continue
            with self._lock:
                if self._finished:
                    return
                if text and text != self._partial:
                    self._partial = text

    # ------------------------------------------------------------------
    # Decoding
    # ------------------------------------------------------------------

    def _transcribe_buffer(self, buffer: bytes) -> tuple[str, float]:
        """Decode *buffer* and return ``(text, confidence)``.  Never raises;
        returns ``("", 0.0)`` on empty input or decode failure."""
        if not buffer:
            return "", 0.0
        try:
            import numpy as np

            audio = (
                np.frombuffer(buffer, dtype=np.int16).astype(np.float32) / 32768.0
            )
        except Exception as exc:
            logger.error("Whisper PCM conversion failed: %s", exc, exc_info=True)
            return "", 0.0
        try:
            model = self._ensure_model()
            with self._decode_lock:
                segments, _info = model.transcribe(
                    audio,
                    language=self._language,
                    beam_size=1,
                    best_of=1,
                    temperature=0.0,
                    without_timestamps=True,
                    vad_filter=self._vad_filter,
                    initial_prompt=_INITIAL_PROMPT,
                    condition_on_previous_text=False,
                )
                segs = list(segments)
        except Exception as exc:
            logger.error("Whisper transcribe failed: %s", exc, exc_info=True)
            return "", 0.0

        if not segs:
            return "", 0.0

        text = "".join(getattr(s, "text", "") or "" for s in segs).strip()
        total_dur = 0.0
        for s in segs:
            total_dur += max(0.0, (getattr(s, "end", 0.0) or 0.0) - (getattr(s, "start", 0.0) or 0.0))
        if total_dur <= 0.0:
            total_dur = float(len(segs))

        confidence = 0.0
        for s in segs:
            dur = max(0.0, (getattr(s, "end", 0.0) or 0.0) - (getattr(s, "start", 0.0) or 0.0))
            weight = dur / total_dur if total_dur else 1.0 / len(segs)
            try:
                base = math.exp(float(getattr(s, "avg_logprob", 0.0) or 0.0))
            except (TypeError, ValueError):
                base = 0.0
            try:
                no_speech = float(getattr(s, "no_speech_prob", 0.0) or 0.0)
            except (TypeError, ValueError):
                no_speech = 0.0
            confidence += weight * base * (1.0 - max(0.0, min(1.0, no_speech)))

        return text, max(0.0, min(1.0, confidence))

    def finalize(self) -> FinalTranscript:
        """End the session and produce a confidence-gated final transcript."""
        with self._lock:
            self._finished = True
            buffer = bytes(self._pcm_buffer)
            duration_ms = 0.0
            if self._started_at is not None:
                duration_ms = (time.monotonic() - self._started_at) * 1000.0

        text, confidence = self._transcribe_buffer(buffer)
        return self._gate(text, confidence, duration_ms)

    def _gate(
        self,
        text: str,
        confidence: float,
        duration_ms: float,
    ) -> FinalTranscript:
        """Apply the confidence gate (mirrors streaming_stt's whole-utterance
        gate so both engines reject the same shapes)."""
        text = " ".join(text.split())
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
            pass_used="whisper",
        )

    # ------------------------------------------------------------------
    # Utilities
    # ------------------------------------------------------------------

    @property
    def is_active(self) -> bool:
        with self._lock:
            return not self._finished

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
        """Drop the session state; a fresh one is created on the next begin()."""
        with self._lock:
            self._finished = True
            self._reset_state()
