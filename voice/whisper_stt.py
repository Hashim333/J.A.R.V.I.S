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
    the authoritative **final** decode uses a small beam (``beam_size<=2``,
    ``temperature=0``) with timestamps and per-word probabilities enabled
    for accuracy at low CPU cost; live partials stay greedy and fast.
    The external capture VAD owns endpointing, so the final decode runs
    with ``vad_filter=False`` (the built-in filter deleted whole accepted
    utterances); no initial prompt is used (prompt echo hallucination
    on weak audio).
  * Confidence is the duration-weighted mean of ``exp(avg_logprob)`` per
    segment, scaled by ``1 - no_speech_prob`` (a segment with no real
    speech collapses toward zero).  **Per-word and per-sentence (segment)
    confidences** are also reported (``word_timestamps=True``), including a
    ``min_word_confidence`` so a garbled word inside an otherwise strong
    command can be spotted.  The same gate rules as the Vosk transcriber
    decide acceptance: threshold, a stricter bar for single words,
    too-short, and no-speech rejection.
  * **Low-confidence retry pass** (FIX-003): when the first decode is
    rejected on confidence, one more decode runs with different settings
    (sampling temperature, no VAD filter, no prompt bias) before the
    utterance is written off — rescuing commands the strict pass clipped.

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
from voice.transcript_quality import is_pathological as _is_pathological, known_app_command

logger = logging.getLogger(__name__)

# Default minimum final confidence for acceptance (matches the Vosk gate).
# Lowered from 0.45 to 0.35 to work better with Whisper base model.
DEFAULT_CONFIDENCE_THRESHOLD = 0.35

# PART 2: evidence-based rescue for short / known commands.  When a clean
# transcript of a *known* command falls below the numeric threshold it is
# accepted on evidence (clean text + known app/command + acceptable per-word
# confidence + voiced duration), NOT by lowering the threshold globally.
CORROBORATED_MIN_CONFIDENCE = 0.25
CORROBORATED_MIN_WORD_CONFIDENCE = 0.10
CORROBORATED_MIN_VOICED_SECONDS = 0.25
# FIX 4: never spend a second full decode on a blip.  Below this much
# measured speech a retry decodes the same near-empty audio and can only
# hallucinate differently at full CPU cost.
MIN_RETRY_VOICED_SECONDS = 0.20

# NOTE: no initial prompt is used (see _decode_kwargs): a prompt is echoed
# back as a fake transcript when the audio signal is weak — confirmed in
# production logs.  Indian-English support comes from the language pin.

# Max buffer length (seconds) that the background partial decoder will
# re-decode — longer captures are left to the authoritative ``finalize``.
_MAX_PARTIAL_SECONDS = 20.0

# VOICE-FIX: buffers below this RMS are near-silence (gate-zeroed / empty
# mic) and must fail fast instead of burning a full Whisper decode that
# returns hallucinations.  Raised from 0.005 to 0.01 for stricter gate.
_SILENCE_RMS_THRESHOLD = 0.01


def _looks_like_speech(text: str) -> bool:
    """Garbage guard for the conversational rescue: at least half the words
    must contain a vowel (real-word shape).  Refuses "zzz qqq"-style
    decoder garbage while accepting "can you hear me"."""
    words = text.split()
    if not words:
        return False
    vowels = set("aeiouy")
    plausible = sum(1 for w in words if vowels & set(w.casefold()))
    return plausible * 2 >= len(words)


def _buffer_rms(buffer: bytes) -> float:
    """RMS of a 16-bit PCM buffer in [0, 1]; 0.0 on failure."""
    try:
        import audioop

        return audioop.rms(buffer, 2) / 32768.0
    except Exception:
        return 0.0


def _model_size() -> str:
    return os.getenv("JARVIS_WHISPER_MODEL", "small")


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


def _model_cached(model_size: str) -> bool:
    """Check if the model is cached locally."""
    import os
    from pathlib import Path
    cache_dir = Path(os.getenv("HF_HOME", Path.home() / ".cache" / "huggingface")) / "hub"
    model_dir = cache_dir / f"models--Systran--faster-whisper-{model_size}"
    return model_dir.exists() and any(model_dir.iterdir())


def _get_shared_model(local_files_only: bool = False):
    """Load the shared Faster-Whisper model once (thread-safe).

    Configurable via ``JARVIS_WHISPER_MODEL`` (default ``small``),
    ``JARVIS_WHISPER_LANG`` (default ``en``) and ``JARVIS_WHISPER_THREADS``.
    """
    global _shared_model
    if _shared_model is None:
        with _model_lock:
            if _shared_model is None:
                from faster_whisper import WhisperModel

                model_size = _model_size()
                # Use offline mode if model is cached
                if not local_files_only:
                    local_files_only = _model_cached(model_size)
                    if local_files_only:
                        os.environ["HF_HUB_OFFLINE"] = "1"
                        logger.info("Whisper: model cached locally, using HF_HUB_OFFLINE=1")
                
                _shared_model = WhisperModel(
                    model_size,
                    device="cpu",
                    compute_type="int8",
                    cpu_threads=_cpu_threads(),
                    local_files_only=local_files_only,
                )
    return _shared_model


def preload_model(wait: bool = False, local_files_only: bool = False) -> threading.Thread | bool:
    """Warm the shared Whisper model so the first capture never stalls.

    The one-time model download/load can take tens of seconds; by default it
    runs on a daemon thread so application startup is not blocked.  Captures
    that start before the load finishes simply wait on the internal model
    lock (the preload is almost always complete by the time a user speaks).

    Args:
        wait: When True, block until the model is loaded (or fails) and return bool.
        local_files_only: When True, use HF_HUB_OFFLINE=1 and local_files_only=True
            to load from cache only (no network).

    Returns:
        If wait=False: the preload thread (can be joined later).
        If wait=True: True when the model is available, False on failure.
    """
    outcome: list[bool] = []

    def _load() -> None:
        try:
            model = _get_shared_model(local_files_only=local_files_only)
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
    return thread


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
        vad_filter: Let the built-in Silero VAD drop non-speech in the
            best-effort partial preview only.  The authoritative final
            decode always runs with ``vad_filter=False`` — the external
            capture VAD owns endpointing (internal filtering deleted whole
            accepted utterances in production).
        beam_size: Beam-search width for the authoritative final decode
            (accuracy-first; partials stay greedy).
        temperature: Sampling temperature for the first decode pass (0 =
            deterministic greedy/beam).
        retry_on_low_confidence: Re-decode with different settings when the
            first decode is rejected on confidence.
        retry_temperature: Sampling temperature for the retry pass.
        word_timestamps: Enable per-word timestamps/probabilities on the
            final decode so per-word confidence can be reported.
    """

    def __init__(
        self,
        sample_rate: int = 16000,
        model_factory: Callable[[], Any] | None = None,
        language: str | None = None,
        confidence_threshold: float = DEFAULT_CONFIDENCE_THRESHOLD,
        min_text_chars: int = 2,
        min_text_words: int = 1,
        single_word_min_confidence: float = 0.5,
        enable_partials: bool = True,
        partial_interval_ms: float = 1200.0,
        vad_filter: bool = True,
        beam_size: int = 3,
        temperature: float = 0.0,
        retry_on_low_confidence: bool = True,
        retry_temperature: float = 0.2,
        word_timestamps: bool = True,
        contextual_acceptance: bool = True,
        corroborate: Callable[[str], bool] | None = None,
        corroborated_min_confidence: float = CORROBORATED_MIN_CONFIDENCE,
        corroborated_min_word_confidence: float = CORROBORATED_MIN_WORD_CONFIDENCE,
        corroborated_min_voiced_seconds: float = CORROBORATED_MIN_VOICED_SECONDS,
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
        self._beam_size = max(1, min(int(beam_size), 3))
        self._temperature = float(temperature)
        self._retry_on_low_confidence = bool(retry_on_low_confidence)
        self._retry_temperature = float(retry_temperature)
        self._word_timestamps = bool(word_timestamps)
        # PART 2: contextual acceptance — rescue known commands that only
        # missed the numeric bar.  ``corroborate`` is injectable so tests
        # can supply their own notion of "known".
        self._contextual_acceptance = bool(contextual_acceptance)
        self._corroborate = corroborate or known_app_command
        self._corroborated_min_confidence = float(corroborated_min_confidence)
        self._corroborated_min_word_confidence = float(corroborated_min_word_confidence)
        self._corroborated_min_voiced_seconds = float(corroborated_min_voiced_seconds)

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
                text, _conf = self._transcribe_buffer(buffer, partial=True)
            except Exception as exc:
                logger.debug("Partial decode skipped: %s", exc)
                continue
            with self._lock:
                if self._finished:
                    return
                # FIX-VOICE-003: only update partial if text changed AND it's
                # not a repetition of the current partial. This prevents
                # pathological repetition from accumulating in the partial.
                if text and text != self._partial:
                    # Check if this is a pathological repetition
                    if not _is_pathological(text):
                        self._partial = text
                    else:
                        logger.warning("Partial decode is pathological - not updating")

    # ------------------------------------------------------------------
    # Decoding
    # ------------------------------------------------------------------

    def _pcm_to_float(self, buffer: bytes) -> Any | None:
        """Convert 16-bit PCM bytes to float32 [-1, 1]; None on failure."""
        try:
            import numpy as np

            return (
                np.frombuffer(buffer, dtype=np.int16).astype(np.float32) / 32768.0
            )
        except Exception as exc:
            logger.error("Whisper PCM conversion failed: %s", exc, exc_info=True)
            return None

    def _decode_kwargs(self, retry: bool = False, action_retry: bool = False) -> dict:
        """Decode settings for the authoritative pass.

        The primary pass uses a small beam (fast on CPU) + timestamps for
        per-word probabilities, language pinned to English. An initial prompt
        with common command phrases improves proper noun recognition
        (e.g., "YouTube", "Chrome", "Python") without causing hallucinations
        on weak audio because the capture VAD already owns endpointing.
        The primary pass sets ``vad_filter=False``: the external capture
        VAD already owns endpointing, and Whisper's internal Silero (fixed
        threshold 0.5 / 2 s min-silence defaults) has been observed deleting
        entire accepted utterances ("VAD filter removed 00:01.424" →
        empty transcript).  ONE authoritative boundary: the capture VAD.
        The retry pass deliberately changes the settings (sampling
        temperature, still no VAD filter) so a command the strict pass
        rejected has a real chance of being rescued.
        The action_retry pass uses even more permissive settings for
        semantically valid action commands.

        Latency note: beam/best_of are clamped to <= 3 — beam 5 on CPU
        int8 costs seconds per utterance with negligible accuracy gain on
        short commands.  The configured values are honoured up to the cap.
        """
        beam = max(1, min(int(self._beam_size), 3))
        
        # Initial prompt with common commands to improve proper noun recognition
        initial_prompt = (
            "Open YouTube, open Chrome, open browser, play music, "
            "search Python, what is Python, tell me a joke, "
            "volume up, volume down, scroll down, click, type."
        )
        
        if action_retry:
            # Most permissive: higher temperature, no prompt bias, greedy-ish
            return {
                "beam_size": 1,
                "best_of": 1,
                "temperature": 0.4,
                "without_timestamps": False,
                "word_timestamps": self._word_timestamps,
                "vad_filter": False,
                "initial_prompt": None,
                "condition_on_previous_text": False,
                "repetition_penalty": 1.2,
                "no_repeat_ngram_size": 3,
            }
        if retry:
            return {
                "beam_size": beam,
                "best_of": beam,
                "temperature": self._retry_temperature,
                "without_timestamps": False,
                "word_timestamps": self._word_timestamps,
                "vad_filter": False,
                "initial_prompt": None,
                "condition_on_previous_text": False,
                "repetition_penalty": 1.5,
                "no_repeat_ngram_size": 3,
            }
        return {
            "beam_size": beam,
            "best_of": beam,
            "temperature": self._temperature,
            "without_timestamps": False,
            "word_timestamps": self._word_timestamps,
            # P0: never let the internal VAD delete the externally accepted
            # utterance.  ``self._vad_filter`` still governs the best-effort
            # partial preview below; the authoritative final always decodes
            # the whole capture buffer.
            "vad_filter": False,
            "initial_prompt": initial_prompt,
            "condition_on_previous_text": False,
            "repetition_penalty": 1.5,
            "no_repeat_ngram_size": 3,
        }

    def _transcribe_buffer(self, buffer: bytes, partial: bool = False) -> tuple[str, float]:
        """Decode *buffer* and return ``(text, confidence)``.  Never raises;
        returns ``("", 0.0)`` on empty input or decode failure.

        ``partial=True`` uses the fast greedy, no-timestamps settings for the
        background partial decoder; the final decode goes through
        :meth:`_transcribe_detailed` instead.
        """
        if not buffer:
            return "", 0.0
        audio = self._pcm_to_float(buffer)
        if audio is None:
            return "", 0.0
        try:
            model = self._ensure_model()
            with self._decode_lock:
                if partial:
                    kwargs = {
                        "beam_size": 1,
                        "best_of": 1,
                        "temperature": 0.0,
                        "without_timestamps": True,
                        "word_timestamps": False,
                        "vad_filter": self._vad_filter,
                        "initial_prompt": None,
                        "condition_on_previous_text": False,
                        "repetition_penalty": 1.3,
                        "no_repeat_ngram_size": 3,
                    }
                else:
                    kwargs = self._decode_kwargs(retry=False)
                segments, _info = model.transcribe(
                    audio, language=self._language, **kwargs
                )
                segs = list(segments)
        except Exception as exc:
            logger.error("Whisper transcribe failed: %s", exc, exc_info=True)
            return "", 0.0

        text, confidence, _, _, _ = self._score_segments(segs)
        return text, confidence

    def _score_segments(
        self, segs: list,
    ) -> tuple[str, float, tuple[tuple[str, float], ...], tuple[tuple[str, float], ...], float | None]:
        """Turn decoded segments into ``(text, confidence, word_confidences,
        sentence_confidences, min_word_confidence)``.

        Overall confidence stays the duration-weighted mean of
        ``exp(avg_logprob)`` scaled by ``1 - no_speech_prob`` (unchanged from
        before).  Per-word probabilities come from ``word_timestamps=True``
        (``segment.words[].probability``); when a segment carries no word
        objects (e.g. injected fakes), its tokens each inherit the segment
        confidence as a fallback.
        """
        if not segs:
            return "", 0.0, (), (), None

        text = "".join(getattr(s, "text", "") or "" for s in segs).strip()
        total_dur = 0.0
        for s in segs:
            total_dur += max(
                0.0, (getattr(s, "end", 0.0) or 0.0) - (getattr(s, "start", 0.0) or 0.0)
            )
        if total_dur <= 0.0:
            total_dur = float(len(segs))

        confidence = 0.0
        sentences: list[tuple[str, float]] = []
        words: list[tuple[str, float]] = []
        for s in segs:
            dur = max(
                0.0, (getattr(s, "end", 0.0) or 0.0) - (getattr(s, "start", 0.0) or 0.0)
            )
            weight = dur / total_dur if total_dur else 1.0 / len(segs)
            try:
                base = math.exp(float(getattr(s, "avg_logprob", 0.0) or 0.0))
            except (TypeError, ValueError):
                base = 0.0
            try:
                no_speech = float(getattr(s, "no_speech_prob", 0.0) or 0.0)
            except (TypeError, ValueError):
                no_speech = 0.0
            sconf = base * (1.0 - max(0.0, min(1.0, no_speech)))
            confidence += weight * sconf

            stext = (getattr(s, "text", "") or "").strip()
            if stext:
                sentences.append((stext, sconf))

            word_list = getattr(s, "words", None)
            if word_list:
                for w in word_list:
                    wtext = (getattr(w, "word", None) or "").strip()
                    wprob = getattr(w, "probability", None)
                    if wtext and wprob is not None:
                        try:
                            words.append(
                                (wtext, max(0.0, min(1.0, float(wprob))))
                            )
                        except (TypeError, ValueError):
                            pass
            else:
                for token in stext.split():
                    words.append((token, sconf))

        min_word = min((p for _, p in words), default=None)
        return (
            text,
            max(0.0, min(1.0, confidence)),
            tuple(words),
            tuple(sentences),
            min_word,
        )

    def _transcribe_detailed(
        self, buffer: bytes, retry: bool = False, action_retry: bool = False,
    ) -> tuple[str, float, tuple[tuple[str, float], ...], tuple[tuple[str, float], ...], float | None]:
        """Full authoritative decode returning text, overall confidence, and
        the per-word / per-sentence confidence metrics.  Never raises."""
        if not buffer:
            return "", 0.0, (), (), None
        audio = self._pcm_to_float(buffer)
        if audio is None:
            return "", 0.0, (), (), None
        try:
            model = self._ensure_model()
            with self._decode_lock:
                segments, _info = model.transcribe(
                    audio, language=self._language, **self._decode_kwargs(retry=retry, action_retry=action_retry)
                )
                segs = list(segments)
        except Exception as exc:
            logger.error("Whisper transcribe failed: %s", exc, exc_info=True)
            return "", 0.0, (), (), None
        return self._score_segments(segs)

    def finalize(self, voiced_seconds: float | None = None) -> FinalTranscript:
        """End the session and produce a confidence-gated final transcript.

        When the first (accuracy-first) decode is rejected purely on
        confidence, a retry pass runs with different decode settings
        (sampling temperature, no VAD filter, no prompt bias) before the
        utterance is written off.  The better result wins — unless the
        retry is corrupted (pathological repetition, dramatic length blow-up,
        or semantic divergence), in which case the original is kept and the
        corruption is never surfaced to the caller (PART 6).

        ``voiced_seconds`` is the capture VAD's measured speech duration;
        it corroborates short known commands so a whisper of a real word is
        not rejected purely on its numeric confidence (PART 2).
        """
        with self._lock:
            self._finished = True
            buffer = bytes(self._pcm_buffer)
            duration_ms = 0.0
            if self._started_at is not None:
                duration_ms = (time.monotonic() - self._started_at) * 1000.0

        # VOICE-FIX: never burn a full Whisper decode on near-silence.
        # A gate-zeroed / empty buffer decodes to hallucinations ("...") or
        # empty text at the cost of seconds of CPU.  Fail fast instead.
        if not buffer or _buffer_rms(buffer) < _SILENCE_RMS_THRESHOLD:
            return self._gate(
                "", 0.0, duration_ms,
                word_confidences=(), sentence_confidences=(),
                min_word_confidence=None, pass_used="whisper",
                voiced_seconds=voiced_seconds,
            )

        text, confidence, words, sentences, min_word = self._transcribe_detailed(buffer)
        final = self._gate(
            text, confidence, duration_ms,
            word_confidences=words,
            sentence_confidences=sentences,
            min_word_confidence=min_word,
            pass_used="whisper",
            voiced_seconds=voiced_seconds,
        )

        # VOICE-FIX: the retry pass doubles latency (two full decodes).
        # Only retry when the first decode produced real, non-pathological
        # text — never for empty / too-short / pathological results where a
        # second decode can only hallucinate differently at full CPU cost.
        # FIX 4: also skip when there is insufficient measured audio behind
        # the decode — re-decoding a blip cannot rescue it.
        if (
            self._retry_on_low_confidence
            and not final.accepted
            and final.rejected_reason == "low confidence"
            and bool(text and text.strip())
            and not _is_pathological(text)
            and (
                voiced_seconds is None
                or voiced_seconds >= MIN_RETRY_VOICED_SECONDS
            )
        ):
            r_text, r_conf, r_words, r_sent, r_min = self._transcribe_detailed(
                buffer, retry=True
            )
            retry_final = self._gate(
                r_text, r_conf, duration_ms,
                word_confidences=r_words,
                sentence_confidences=r_sent,
                min_word_confidence=r_min,
                pass_used="whisper-retry",
                voiced_seconds=voiced_seconds,
            )
            if self._retry_corrupted(final, retry_final):
                # PART 6: a decoder run-away must never override (or even
                # surface as) a clean transcript.  Keep the original result;
                # the corrupted retry is discarded with a diagnostic reason.
                logger.warning(
                    "RETRY PASS rejected as corrupt/divergent: %r (%.3f) -> "
                    "%r (%.3f) — discarding retry",
                    final.text, final.confidence,
                    retry_final.text, retry_final.confidence,
                )
            elif retry_final.accepted or retry_final.confidence > final.confidence:
                logger.info(
                    "RETRY PASS rescued low-confidence decode: %r (%.3f) -> "
                    "%r (%.3f, accepted=%s)",
                    final.text, final.confidence,
                    retry_final.text, retry_final.confidence, retry_final.accepted,
                )
                final = retry_final
            elif retry_final.text != final.text:
                logger.info(
                    "RETRY PASS did not improve: %r (%.3f) vs %r (%.3f)",
                    final.text, final.confidence,
                    retry_final.text, retry_final.confidence,
                )

        # VOICE-FIX: Second retry pass for action commands that are
        # semantically valid but still below confidence threshold. This uses
        # even more permissive settings (higher temperature, no initial prompt)
        # to rescue commands like "open YouTube" that may have been misrecognized.
        if (
            self._retry_on_low_confidence
            and not final.accepted
            and final.rejected_reason == "low confidence"
            and bool(final.text and final.text.strip())
            and not _is_pathological(final.text)
            and self._looks_like_action_command(final.text)
            and (
                voiced_seconds is None
                or voiced_seconds >= MIN_RETRY_VOICED_SECONDS
            )
        ):
            r2_text, r2_conf, r2_words, r2_sent, r2_min = self._transcribe_detailed(
                buffer, retry=True, action_retry=True
            )
            retry2_final = self._gate(
                r2_text, r2_conf, duration_ms,
                word_confidences=r2_words,
                sentence_confidences=r2_sent,
                min_word_confidence=r2_min,
                pass_used="whisper-retry2-action",
                voiced_seconds=voiced_seconds,
            )
            if self._retry_corrupted(final, retry2_final):
                logger.warning(
                    "RETRY2 PASS (action) rejected as corrupt/divergent: %r (%.3f) -> "
                    "%r (%.3f) — discarding retry",
                    final.text, final.confidence,
                    retry2_final.text, retry2_final.confidence,
                )
            elif retry2_final.accepted or retry2_final.confidence > final.confidence:
                logger.info(
                    "RETRY2 PASS (action) rescued low-confidence action command: %r (%.3f) -> "
                    "%r (%.3f, accepted=%s)",
                    final.text, final.confidence,
                    retry2_final.text, retry2_final.confidence, retry2_final.accepted,
                )
                final = retry2_final
            elif retry2_final.text != final.text:
                logger.info(
                    "RETRY2 PASS (action) did not improve: %r (%.3f) vs %r (%.3f)",
                    final.text, final.confidence,
                    retry2_final.text, retry2_final.confidence,
                )
        return final

    def _looks_like_action_command(self, text: str) -> bool:
        """Check if text looks like a computer-control action command.
        This is used to trigger a second retry pass for action commands."""
        text_lower = text.lower().strip()
        if not text_lower:
            return False

        # Action verb patterns that indicate a computer-control command
        action_patterns = [
            r'^(open|launch|start|run|go to)\s+\w+',
            r'^(search|find|look up|google)\s+(for\s+)?\w+',
            r'^(search|find|look up)\s+\w+\s+(for|on|in)\s+\w+',
            r'^(play|pause|resume|stop)\s+\w+',
            r'^(play|pause|resume|stop)\s+(the\s+)?(first|second|third|next|previous|video|song|music)\b',
            r'^(click|tap|press)\s+(the\s+)?(first|second|third|link|button|video|result)\b',
            r'^(scroll|page)\s+(up|down|top|bottom)\b',
            r'^(go|navigate)\s+(back|forward|home)\b',
            r'^(type|enter|input)\s+',
            r'^(volume|mute|unmute)\s+(up|down|on|off)?\b',
            r'^(close|quit|exit|stop|kill)\s+\w+',
            r'^(focus|switch to|bring to)\s+\w+',
        ]

        import re
        for pattern in action_patterns:
            if re.search(pattern, text_lower):
                return True
        return False

    def _retry_corrupted(self, original: FinalTranscript, retry: FinalTranscript) -> bool:
        """PART 6: True when the retry result is a decoder hallucination and
        must not replace the original: pathological repetition, a dramatic
        length blow-up with no supporting evidence, catastrophic per-word
        confidence, or near-total semantic divergence.

        FIX-VOICE-002: Normalize harmless differences before comparison:
        punctuation-only differences, case differences, and minor spacing
        variations should NOT be treated as divergent results.
        """
        if not retry.text or not retry.text.strip():
            return False
        if _is_pathological(retry.text):
            return True
        o_words = len(original.text.split())
        r_words = len(retry.text.split())
        if r_words > max(4, 3 * max(1, o_words)):
            return True
        if (
            retry.min_word_confidence is not None
            and retry.min_word_confidence < 0.1
        ):
            return True
        from voice.transcript_quality import _words

        # FIX-VOICE-002: Normalize both texts before token comparison
        # to ignore harmless differences (punctuation, case, extra spaces)
        def _normalize_for_comparison(text: str) -> set:
            """Normalize text for comparison, ignoring punctuation, case, and spacing."""
            import re
            # Remove punctuation, convert to lowercase, split into words
            normalized = re.sub(r'[.,!?;:\'"\'\"\`]', '', text.lower().strip())
            return set(_words(normalized))

        o_tokens = _normalize_for_comparison(original.text)
        r_tokens = _normalize_for_comparison(retry.text)
        if o_tokens and r_tokens:
            overlap = len(o_tokens & r_tokens) / len(o_tokens)
            if overlap < 0.3:
                return True
        return False

    def _gate(
        self,
        text: str,
        confidence: float,
        duration_ms: float,
        word_confidences: tuple[tuple[str, float], ...] = (),
        sentence_confidences: tuple[tuple[str, float], ...] = (),
        min_word_confidence: float | None = None,
        pass_used: str = "whisper",
        voiced_seconds: float | None = None,
    ) -> FinalTranscript:
        """Apply the confidence gate (mirrors streaming_stt's whole-utterance
        gate so both engines reject the same shapes).

        PART 5/6: pathological repetition is rejected regardless of
        confidence — a decoder run-away must never be accepted as a command.
        PART 2: a *known* command that merely missed the numeric bar is
        accepted on evidence (clean text + known command + acceptable
        per-word confidence + voiced duration) instead of being refused.
        FIX-VOICE-003: lowered thresholds to accept more valid commands.
        """
        text = " ".join(text.split())
        reason = ""
        if not text:
            reason = "no speech recognized"
        elif _is_pathological(text):
            reason = "pathological repetition"
        elif len(text) < self._min_text_chars:
            reason = "too short"
        elif len(text.split()) < self._min_text_words:
            reason = f"too short ({len(text.split())} word(s))"
        elif len(text.split()) == 1 and confidence < self._single_word_min_confidence:
            reason = "low confidence"
        elif confidence < self._confidence_threshold:
            reason = "low confidence"

        if reason == "low confidence" and self._contextual_acceptance:
            word_ok = (
                min_word_confidence is None
                or min_word_confidence >= self._corroborated_min_word_confidence
            )
            voiced_ok = (
                voiced_seconds is None
                or voiced_seconds >= self._corroborated_min_voiced_seconds
            )
            if (
                confidence >= self._corroborated_min_confidence
                and word_ok and voiced_ok and self._corroborate(text)
            ):
                logger.info(
                    "STT corroborated known command below threshold: %r "
                    "(confidence=%.3f min_word=%s voiced=%ss) -> accepted",
                    text, confidence,
                    f"{min_word_confidence:.3f}" if min_word_confidence is not None else "-",
                    f"{voiced_seconds:.2f}" if voiced_seconds is not None else "-",
                )
                reason = ""
            elif (
                confidence >= self._corroborated_min_confidence
                and voiced_ok and not _is_pathological(text)
                and len(text.split()) >= 2 and len(text) >= 6
                and _looks_like_speech(text)
            ):
                # VOICE-FIX: ordinary conversational speech ("can you hear
                # me?", "what time is it") is evidence-accepted on voiced
                # duration + plausibility — never rejected purely because a
                # numeric threshold was missed.  Single words still need the
                # higher bar above; pathological output is still refused.
                logger.info(
                    "STT accepted plausible conversational speech below "
                    "threshold: %r (confidence=%.3f voiced=%ss)",
                    text, confidence,
                    f"{voiced_seconds:.2f}" if voiced_seconds is not None else "-",
                )
                reason = ""
        return FinalTranscript(
            text=text,
            confidence=confidence,
            accepted=(not reason),
            duration_ms=duration_ms,
            rejected_reason=reason,
            pass_used=pass_used,
            word_confidences=word_confidences,
            sentence_confidences=sentence_confidences,
            min_word_confidence=min_word_confidence,
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
