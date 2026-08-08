"""
voice/pipeline/wake.py

``WakeWordManager`` — the always-on, low-CPU wake listener.

Sleep Mode keeps *only* this component active.  Every cleaned mic chunk is
pushed through a VAD-gated local Vosk check for "jarvis"; the heavyweight
STT/LLM/TTS/automation components are never loaded or run while asleep, so
idle CPU/RAM stay minimal.  When the phrase is confirmed the manager fires
``on_wake`` and the pipeline flips to Conversation Mode.

Wraps the existing :class:`voice.wakeword.WakeWordDetector` (VAD -> Vosk),
which already rejects non-wake speech and only emits genuine hits.
"""
from __future__ import annotations

import logging
import time
from typing import Callable

from voice.wakeword import WakeWordDetector

logger = logging.getLogger(__name__)


class WakeWordManager:
    """Continuous, low-CPU wake-word listening.

    Args:
        sample_rate: Pipeline rate (16 kHz).
        detector_factory: Returns a ``WakeWordDetector`` (injected for tests).
        on_wake: Called (mic thread) with the captured wake audio when the
            phrase is confirmed.
        on_wake_latency: Optional ``(latency_ms) -> None`` callback used to
            record the wake->ack latency in the request log.
    """

    def __init__(
        self,
        sample_rate: int = 16000,
        detector_factory: Callable[[], WakeWordDetector] | None = None,
        on_wake: Callable[[object], None] | None = None,
        on_wake_latency: Callable[[float], None] | None = None,
    ) -> None:
        self._sample_rate = sample_rate
        self._on_wake = on_wake
        self._on_wake_latency = on_wake_latency
        self._detector_factory = detector_factory or (
            lambda: WakeWordDetector(
                on_wake_word_detected=self._on_wake_word_detected,
                sample_rate=sample_rate,
            )
        )
        self._detector: WakeWordDetector | None = None
        self._armed = False
        self._suspected_at: float | None = None

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def arm(self) -> None:
        """Begin listening for the wake phrase (Sleep Mode)."""
        if self._detector is None:
            self._detector = self._detector_factory()
        self._detector.reset()
        self._armed = True
        self._suspected_at = None
        logger.info("WakeWordManager armed")

    def disarm(self) -> None:
        """Pause wake listening (Conversation Mode is active)."""
        self._armed = False
        self._suspected_at = None
        logger.info("WakeWordManager disarmed")

    def feed(self, clean_chunk: bytes) -> None:
        """Feed a cleaned mic chunk while armed (mic thread)."""
        if not self._armed or self._detector is None:
            return
        try:
            self._detector.process_audio(clean_chunk)
        except Exception as exc:
            logger.error("WakeWordManager feed failed: %s", exc, exc_info=True)

    def reset(self) -> None:
        """Re-arm for the next wake word without closing the detector."""
        if self._detector is not None:
            self._detector.reset()
        self._suspected_at = None
        logger.info("WakeWordManager reset")

    def shutdown(self) -> None:
        self._armed = False
        self._detector = None

    # ------------------------------------------------------------------
    # Detector callback
    # ------------------------------------------------------------------

    def _on_wake_word_detected(self, audio_data: object) -> None:
        if not self._armed:
            return
        if self._suspected_at is None:
            self._suspected_at = time.monotonic()
        latency_ms = (time.monotonic() - self._suspected_at) * 1000.0
        logger.info("Wake word confirmed (latency=%.1f ms)", latency_ms)
        if self._on_wake_latency is not None:
            try:
                self._on_wake_latency(latency_ms)
            except Exception as exc:
                logger.error("on_wake_latency failed: %s", exc, exc_info=True)
        if self._on_wake is not None:
            try:
                self._on_wake(audio_data)
            except Exception as exc:
                logger.error("on_wake callback failed: %s", exc, exc_info=True)

    # ------------------------------------------------------------------

    @property
    def armed(self) -> bool:
        return self._armed