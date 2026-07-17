"""
services/listener_service.py

A service responsible for capturing and transcribing a single spoken command.
"""

from __future__ import annotations

import logging
from typing import Any

from services.base_service import BaseService
from voice.microphone import MicrophoneManager
from voice.speech_recognition import SpeechRecognition, SpeechRecognitionResult

logger = logging.getLogger(__name__)


class ListenerService(BaseService):
    """
    Orchestrates the process of listening for a single command and
    transcribing it to text.

    This service does not perform wake-word detection. It is designed to be
    activated on-demand to capture a command after a wake-word has already
    been detected by another service.
    """

    def __init__(
        self,
        microphone_manager: MicrophoneManager | None = None,
        speech_recognition: SpeechRecognition | None = None,
        max_retries: int = 2,
    ) -> None:
        """
        Initializes the ListenerService.

        Args:
            microphone_manager: An instance to handle one-shot audio capture.
            speech_recognition: An instance to handle audio-to-text transcription.
            max_retries: Number of times to retry listening on failure.
        """
        super().__init__(name="listener")
        self._microphone_manager = microphone_manager or MicrophoneManager()
        self._speech_recognition = speech_recognition or SpeechRecognition()
        self._max_retries = max_retries

    def listen_for_command(self, timeout: float | None = None) -> SpeechRecognitionResult:
        """
        Captures a single utterance from the microphone and returns the
        transcription result with retries.

        This is a blocking operation that will listen until speech is detected
        and transcribed, or until a timeout occurs.

        Returns:
            A SpeechRecognitionResult object containing the outcome.
        """
        attempts = 0
        max_attempts = self._max_retries + 1
        while attempts < max_attempts:
            attempts += 1
            logger.debug(
                "Listening for command (attempt %d/%d)", attempts, max_attempts
            )
            capture = self._microphone_manager.capture_once()
            if not capture.success:
                logger.warning(
                    "Microphone capture failed (attempt %d/%d): %s",
                    attempts, max_attempts, capture.error
                )
                if attempts < max_attempts:
                    continue
                return SpeechRecognitionResult(success=False, error=capture.error)

            result = self._speech_recognition.recognize(capture.audio)
            if result.success and result.text:
                logger.info("Command recognized: '%s'", result.text)
                return result

            logger.warning(
                "Speech recognition failed (attempt %d/%d): %s",
                attempts, max_attempts, result.error
            )
            if attempts < max_attempts:
                continue

            return result

        return SpeechRecognitionResult(
            success=False, error="Failed to capture command after retries."
        )

    def transcribe(self, audio_data: Any) -> SpeechRecognitionResult:
        """
        Transcribe pre-captured audio without opening the microphone.

        This is the companion to :meth:`listen_for_command`: it performs
        the same transcription step without the microphone capture step.
        Used to transcribe audio captured during wake-word detection.

        Args:
            audio_data: An ``sr.AudioData`` instance (or anything the
                speech recognition engine accepts).

        Returns:
            A SpeechRecognitionResult.
        """
        return self._speech_recognition.recognize(audio_data)

    def initialize(self) -> None:
        """No-op. Resources are managed on-demand by collaborators."""
        pass

    def start(self) -> None:
        """No-op. This service is not a long-running process."""
        pass

    def stop(self) -> None:
        """No-op. This service does not have a running state to stop."""
        pass