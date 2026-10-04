"""
services/wake_word_service.py

Wake-word listening for the full-duplex voice redesign.

Previously this service owned the audio consumer on the MicrophoneStream
and its own ``WakeWordDetector``.  In the full-duplex design the
``DuplexVoiceSession`` owns the single microphone consumer and feeds the
*wake detector* (and, separately, the capture/barge-in VADs) with
echo-cancelled, noise-suppressed audio.  This service therefore becomes a
thin adapter over the session's wake detection so its public API
(``start`` / ``stop`` / ``reset_for_wake`` / ``get_command_audio``) and its
role as a registered service remain unchanged.

VOICE-PIPELINE-004: JARVIS operates WITHOUT a wake word — the owner enters
the listen/capture loop directly when IDLE.  The wake detector therefore
stays disabled: ``start`` and ``reset_for_wake`` are no-ops so Vosk never
loads, while ``stop`` / ``shutdown`` remain as defensive pause calls.
"""

from __future__ import annotations

import logging
import threading
from typing import Any

from services.base_service import BaseService
from voice.microphone_stream import MicrophoneStream

logger = logging.getLogger(__name__)


class WakeWordService(BaseService):
    """
    Adapter for wake-word detection delegated to the DuplexVoiceSession.

    VOICE-PIPELINE-004: wake detection is DISABLED by default (direct
    listening, no wake word).  ``start`` / ``reset_for_wake`` are no-ops so
    Vosk never loads.  ``stop`` / ``shutdown`` remain defensive pause calls
    for service lifecycle compatibility.
    """

    def __init__(
        self,
        wake_word_detected_event: threading.Event,
        microphone_stream: MicrophoneStream | None = None,
        session: Any | None = None,
        bridge=None,
    ) -> None:
        super().__init__(name="wake_word")
        self._wake_word_detected_event = wake_word_detected_event
        self._microphone_stream = microphone_stream
        self._session = session
        self._command_audio: Any = None
        self._bridge = bridge

    # ------------------------------------------------------------------
    # Configuration
    # ------------------------------------------------------------------

    def set_session(self, session: Any) -> None:
        """Attach the full-duplex session that owns wake detection."""
        self._session = session

    def initialize(self) -> None:
        """No-op — VOICE-PIPELINE-004 keeps wake detection disabled."""
        logger.info("WakeWordService initialized (wake detection disabled)")

    # ------------------------------------------------------------------
    # Public API (unchanged)
    # ------------------------------------------------------------------

    def reset_for_wake(self) -> None:
        """No-op under VOICE-PIPELINE-004 (direct listening, no wake word).

        JARVIS listens for commands directly while IDLE, so the wake detector
        stays disabled (Vosk never loads).  The conversation manager still
        calls this on every return to idle; the call is intentionally inert.
        """
        self._command_audio = None
        if self._session is not None:
            self._session.reset_wake()
            self._session.start_wake_detection()

    def start(self) -> None:
        """No-op under VOICE-PIPELINE-004 (direct listening, no wake word).

        The wake detector must not be armed, so ``start`` never arms it and
        Vosk remains inactive.
        """
        self.reset_for_wake()

    def stop(self) -> None:
        """Pause wake-word detection."""
        logger.info("WakeWordService stopping")
        if self._session is not None:
            try:
                self._session.stop_wake_detection()
            except Exception as exc:
                logger.error("WakeWordService.stop failed: %s", exc)

    def shutdown(self) -> None:
        """Pause wake-word detection.  The session is owned by run.py."""
        logger.info("WakeWordService shutting down")
        if self._session is not None:
            try:
                self._session.stop_wake_detection()
            except Exception as exc:
                logger.error("WakeWordService.shutdown failed: %s", exc)

    # ------------------------------------------------------------------
    # Session callback
    # ------------------------------------------------------------------

    def _on_wake_word(self, audio_data: Any) -> None:
        """Store the captured command audio and signal the backend loop."""
        try:
            self._command_audio = audio_data
            self._wake_word_detected_event.set()
            # Emit WAKE state
            if self._bridge is not None:
                try:
                    self._bridge.emit_wake("Wake word detected")
                except Exception as exc:
                    logger.debug("Bridge state emit failed: %s", exc)
            try:
                audio_bytes = len(audio_data.frame_data)
            except Exception:
                audio_bytes = -1
            logger.info(
                "Wake word detected — event set (command audio %d bytes)",
                audio_bytes,
            )
        except Exception as exc:
            logger.error("_on_wake_word callback failed: %s", exc, exc_info=True)

    def get_command_audio(self) -> Any:
        return self._command_audio
