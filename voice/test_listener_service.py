"""
dev_tests/test_listener_service.py

Unit tests for the ListenerService.
"""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock

from services.listener_service import ListenerService
from voice.microphone import MicrophoneCapture
from voice.speech_recognition import SpeechRecognitionResult


class TestListenerService(unittest.TestCase):
    """Unit tests for the ListenerService."""

    def setUp(self) -> None:
        """Set up mock dependencies for each test."""
        self.mock_microphone_manager = MagicMock()
        self.mock_speech_recognition = MagicMock()

        self.service = ListenerService(
            microphone_manager=self.mock_microphone_manager,
            speech_recognition=self.mock_speech_recognition,
        )

    def test_successful_command_capture(self) -> None:
        """
        Verify the service correctly orchestrates a successful command capture
        and transcription.
        """
        # Arrange: Simulate successful audio capture and transcription
        fake_audio = "fake_audio_data"
        self.mock_microphone_manager.capture_once.return_value = MicrophoneCapture(
            success=True, audio=fake_audio
        )
        self.mock_speech_recognition.recognize.return_value = SpeechRecognitionResult(
            success=True, text="open notepad"
        )

        # Act: Run the command listener
        result = self.service.listen_for_command()

        # Assert: Verify the flow and the final result
        self.mock_microphone_manager.capture_once.assert_called_once()
        self.mock_speech_recognition.recognize.assert_called_once_with(fake_audio)
        self.assertTrue(result.success)
        self.assertEqual(result.text, "open notepad")

    def test_microphone_capture_failure(self) -> None:
        """
        Verify the service handles a failure from the MicrophoneManager
        and does not proceed to speech recognition.
        """
        # Arrange: Simulate a microphone capture failure
        self.mock_microphone_manager.capture_once.return_value = MicrophoneCapture(
            success=False, error="Microphone not found."
        )

        # Act: Run the command listener
        result = self.service.listen_for_command()

        # Assert: Verify retries (max_retries=2 -> 3 attempts), then failure
        self.assertEqual(self.mock_microphone_manager.capture_once.call_count, 3)
        self.mock_speech_recognition.recognize.assert_not_called()
        self.assertFalse(result.success)
        self.assertEqual(result.error, "Microphone not found.")

    def test_speech_recognition_failure(self) -> None:
        """
        Verify the service handles a failure from the SpeechRecognition component.
        """
        # Arrange: Simulate successful capture but failed recognition
        self.mock_microphone_manager.capture_once.return_value = MicrophoneCapture(
            success=True, audio="fake_audio_data"
        )
        self.mock_speech_recognition.recognize.return_value = SpeechRecognitionResult(
            success=False, error="No speech could be recognized."
        )

        # Act: Run the command listener
        result = self.service.listen_for_command()

        # Assert: Verify the result reflects the recognition failure
        self.assertFalse(result.success)
        self.assertEqual(result.error, "No speech could be recognized.")


if __name__ == "__main__":
    unittest.main()