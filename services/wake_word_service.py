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

    The session performs detection on echo-cancelled audio (so JARVIS's own
    TTS and background music cannot wake it) and calls ``on_wake_word`` with
    the captured command audio; this service stores that audio and sets the
    ``wake_word_detected`` event.
    """

    def __init__(
        self,
        wake_word_detected_event: threading.Event,
        microphone_stream: MicrophoneStream | None = None,
        session: Any | None = None,
    ) -> None:
        super().__init__(name="wake_word")
        self._wake_word_detected_event = wake_word_detected_event
        self._microphone_stream = microphone_stream
        self._session = session
        self._command_audio: Any = None

    # ------------------------------------------------------------------
    # Configuration
    # ------------------------------------------------------------------

    def set_session(self, session: Any) -> None:
        """Attach the full-duplex session that owns wake detection."""
        self._session = session
        if session is not None:
            session.on_wake_word = self._on_wake_word

    def initialize(self) -> None:
        """No-op — the session lazily creates its wake detector."""
        logger.info("WakeWordService initialized (delegates to duplex session)")

    # ------------------------------------------------------------------
    # Public API (unchanged)
    # ------------------------------------------------------------------

    def reset_for_wake(self) -> None:
        """Reset detection and re-arm for the next wake word."""
        logger.info("WakeWordService resetting for next wake word")
        self._command_audio = None
        if self._session is not None:
            try:
                self._session.reset_wake()
                self._session.start_wake_detection()
            except Exception as exc:
                logger.error("reset_for_wake failed: %s", exc)

    def start(self) -> None:
        """Begin listening for the wake word (session-owned consumer)."""
        logger.info("WakeWordService starting — listening for wake word")
        if self._session is not None:
            try:
                self._session.start_wake_detection()
            except Exception as exc:
                logger.error("WakeWordService.start failed: %s", exc)

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
