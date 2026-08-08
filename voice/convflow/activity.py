"""
voice/pipeline/activity.py

``VoiceActivityDetector`` — the strict end-of-speech gate for Conversation Mode.

Wraps the existing adaptive :class:`voice.vad.VAD` with the redesign's exact
contract:

    * fast onset so the first syllable is never clipped,
    * a **1500 ms** silence hangover before an utterance is declared done
      (mid-sentence pauses do not chop the command in half),
    * an immediate ``on_speech_started`` callback so the pipeline can flip to
      LISTENING the instant the user begins,
    * ``on_no_speech`` when audio runs with no speech at all so the
      orchestrator can return to Sleep instead of waiting a hard timeout.

The detector runs on the mic thread; callbacks hop onto the event queue so
they never block audio capture.
"""
from __future__ import annotations

import logging
import time
from typing import Callable

from voice.vad import VAD

logger = logging.getLogger(__name__)

DEFAULT_SILENCE_HANGOVER_MS = 1500.0


class VoiceActivityDetector:
    """Speech-boundary detection for one capture window.

    Args:
        silence_hangover_ms: Sustained silence that ends the utterance.
        min_speech_ms: Minimum speech before an end can fire (rejects blips).
        max_utterance_ms: Hard cap; forces an end for extremely long audio.
        onset_frames: Voiced frames required to declare speech started.
        sample_rate: Pipeline rate (16 kHz mono 16-bit).
        vad: Optional pre-built ``VAD`` (injected in tests).
    """

    def __init__(
        self,
        on_speech_started: Callable[[], None] | None = None,
        on_speech_ended: Callable[[], None] | None = None,
        on_no_speech: Callable[[], None] | None = None,
        silence_hangover_ms: float = DEFAULT_SILENCE_HANGOVER_MS,
        min_speech_ms: float = 250.0,
        max_utterance_ms: float = 20000.0,
        onset_frames: int = 3,
        sample_rate: int = 16000,
        vad: VAD | None = None,
    ) -> None:
        self._on_speech_started = on_speech_started
        self._on_speech_ended = on_speech_ended
        self._on_no_speech = on_no_speech
        self._silence_hangover_ms = float(silence_hangover_ms)
        self._sample_rate = sample_rate

        self._vad = vad or VAD(
            on_speech_started=self._started,
            on_speech_ended=self._ended,
            sample_rate=sample_rate,
            silence_hangover_ms=self._silence_hangover_ms,
            min_speech_ms=min_speech_ms,
            max_utterance_ms=max_utterance_ms,
            onset_frames=onset_frames,
        )
        if vad is not None:
            # Injection contract: an externally-provided VAD still routes its
            # boundary events through this detector's handlers.
            if hasattr(vad, "on_speech_started"):
                vad.on_speech_started = self._started
            if hasattr(vad, "on_speech_ended"):
                vad.on_speech_ended = self._ended

        self._started_at: float | None = None
        self._speaking = False
        self._heard_any_speech = False
        self._monitoring_silence = False
        self._silence_started_at: float | None = None
        self._no_speech_timeout: float = 8.0

    # ------------------------------------------------------------------
    # Feed
    # ------------------------------------------------------------------

    def begin(self, no_speech_timeout: float = 8.0) -> None:
        """Start a fresh capture window (resets boundary state)."""
        self._vad.reset()
        self._started_at = None
        self._speaking = False
        self._heard_any_speech = False
        self._monitoring_silence = True
        self._silence_started_at = time.monotonic()
        self._no_speech_timeout = float(no_speech_timeout)

    def process_audio(self, chunk: bytes) -> None:
        """Feed a 16-bit PCM chunk through the VAD."""
        if not chunk:
            return
        self._vad.process_audio(chunk)
        if (
            self._monitoring_silence
            and not self._speaking
            and self._started_at is None
            and self._silence_started_at is not None
            and (time.monotonic() - self._silence_started_at) >= self._no_speech_timeout
        ):
            # No speech at all in the window — report so the orchestrator can
            # return to Sleep rather than burning CPU until a hard deadline.
            self._monitoring_silence = False
            if self._on_no_speech:
                try:
                    self._on_no_speech()
                except Exception as exc:
                    logger.error("on_no_speech callback failed: %s", exc, exc_info=True)

    # ------------------------------------------------------------------
    # VAD callbacks (mic thread)
    # ------------------------------------------------------------------

    def _started(self) -> None:
        self._speaking = True
        self._heard_any_speech = True
        self._started_at = time.monotonic()
        logger.debug("VoiceActivityDetector: speech started")
        self._safe(self._on_speech_started, "on_speech_started")

    def _ended(self) -> None:
        self._speaking = False
        logger.debug("VoiceActivityDetector: speech ended")
        self._safe(self._on_speech_ended, "on_speech_ended")

    @staticmethod
    def _safe(callback: Callable[[], None] | None, name: str) -> None:
        if callback is None:
            return
        try:
            callback()
        except Exception as exc:
            logger.error("%s callback failed: %s", name, exc, exc_info=True)

    # ------------------------------------------------------------------
    # State
    # ------------------------------------------------------------------

    @property
    def speaking(self) -> bool:
        return self._speaking

    @property
    def heard_speech(self) -> bool:
        return self._heard_any_speech

    @property
    def started_at(self) -> float | None:
        return self._started_at

    def reset(self) -> None:
        self._vad.reset()
        self._started_at = None
        self._speaking = False
        self._heard_any_speech = False
        self._monitoring_silence = False
        self._silence_started_at = None