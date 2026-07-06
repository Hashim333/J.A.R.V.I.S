"""
services/listener_service.py

A service responsible for capturing and transcribing a single spoken command.
"""

from __future__ import annotations

from services.base_service import BaseService
from voice.microphone import MicrophoneManager
from voice.speech_recognition import SpeechRecognition, SpeechRecognitionResult


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
    ) -> None:
        """
        Initializes the ListenerService.

        Args:
            microphone_manager: An instance to handle one-shot audio capture.
                If None, a default instance is created.
            speech_recognition: An instance to handle audio-to-text transcription.
                If None, a default instance is created.
        """
        super().__init__(name="listener")
        self._microphone_manager = microphone_manager or MicrophoneManager()
        self._speech_recognition = speech_recognition or SpeechRecognition()

    def listen_for_command(self) -> SpeechRecognitionResult:
        """
        Captures a single utterance from the microphone and returns the
        transcription result.

        This is a blocking operation that will listen until speech is detected
        and transcribed, or until a timeout occurs.

        Returns:
            A SpeechRecognitionResult object containing the outcome.
        """
        capture = self._microphone_manager.capture_once()
        if not capture.success:
            return SpeechRecognitionResult(success=False, error=capture.error)

        return self._speech_recognition.recognize(capture.audio)

    def initialize(self) -> None:
        """No-op. Resources are managed on-demand by collaborators."""
        pass

    def start(self) -> None:
        """No-op. This service is not a long-running process."""
        pass

    def stop(self) -> None:
        """No-op. This service does not have a running state to stop."""
        pass