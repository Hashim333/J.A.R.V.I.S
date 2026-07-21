"""
services/wake_word_service.py

The Wake Word Service is responsible for listening for a specific wake word
(e.g., "Jarvis") in the user's speech and detecting voice activity.

It uses a MicrophoneStream (injected, not owned) to receive audio chunks
and a WakeWordDetector that combines VAD + local Vosk detection to confirm
the wake phrase ("jarvis") before signalling the event with the captured
command audio.

The MicrophoneStream lifecycle (start / shutdown) is managed by run.py;
this service only sets and clears the audio consumer.
"""

from __future__ import annotations

import logging
import threading
from typing import Any, Callable

from services.base_service import BaseService
from voice.microphone_stream import MicrophoneStream

logger = logging.getLogger(__name__)


class WakeWordService(BaseService):
    """
    A service that listens for a wake word in the background.

    When the wake word is confirmed, the *raw command audio* (including
    the wake word) is stored and can be retrieved via
    :meth:`get_command_audio`. No transcription is performed inside this
    service — the calling code (``run.py``) is responsible for sending the
    audio to ``ListenerService.transcribe()`` for a single Google STT call.
    """

    def __init__(
        self,
        wake_word_detected_event: threading.Event,
        microphone_stream: MicrophoneStream,
    ) -> None:
        super().__init__(name="wake_word")
        self._wake_word_detected_event = wake_word_detected_event
        self._microphone_stream = microphone_stream
        self._wake_word_detector: Any = None
        self._command_audio: Any = None

    def initialize(self) -> None:
        """
        Initializes the WakeWordDetector (one-time setup).
        MicrophoneStream is already created and owned by run.py.
        """
        try:
            from voice.wakeword import WakeWordDetector

            self._wake_word_detector = WakeWordDetector(
                on_wake_word_detected=self._on_wake_word_detected,
            )
            logger.info("WakeWordService initialized")
        except Exception as e:
            if "Microphone not found" not in str(e):
                logger.error("WakeWordService initialization failed: %s", e)
                raise

    def reset_for_wake(self) -> None:
        """
        Reset detection state and re-attach the consumer.

        Called after a wake word was detected, to prepare for the next one.
        The MicrophoneStream stays open — only the consumer is swapped.
        """
        logger.info("WakeWordService resetting for next wake word")
        self._command_audio = None
        if self._wake_word_detector is not None:
            self._wake_word_detector.reset()
        self._microphone_stream.set_consumer(
            self._wake_word_detector.process_audio
        )

    def _on_wake_word_detected(self, audio_data: Any) -> None:
        """Callback for when the wake phrase is confirmed."""
        try:
            self._command_audio = audio_data
            self._wake_word_detected_event.set()
            logger.info("Wake word detected — event set")
        except Exception as exc:
            logger.error("_on_wake_word_detected callback failed: %s", exc, exc_info=True)

    def get_command_audio(self) -> Any:
        return self._command_audio

    def start(self) -> None:
        """Route audio from the running MicrophoneStream to the wake-word detector."""
        logger.info("WakeWordService starting — listening for wake word")
        self._microphone_stream.set_consumer(
            self._wake_word_detector.process_audio
        )

    def stop(self) -> None:
        """Pause wake-word detection (consumer set to None)."""
        logger.info("WakeWordService stopping")
        self._microphone_stream.set_consumer(None)

    def shutdown(self) -> None:
        """
        Release wake-word resources.

        Does **not** close the MicrophoneStream — that is owned by run.py.
        """
        logger.info("WakeWordService shutting down")
        self._microphone_stream.set_consumer(None)
