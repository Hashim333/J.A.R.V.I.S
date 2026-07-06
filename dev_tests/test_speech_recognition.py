"""
dev_tests/test_speech_recognition.py

Unit tests for the SpeechRecognition adapter.
"""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock

from voice.speech_recognition import SpeechRecognition, SpeechRecognitionResult


class FakeRecognizer:
    """A mock recognizer for testing dependency injection."""

    def __init__(
        self, *, text: str = "open chrome", recognize_error: Exception | None = None
    ) -> None:
        self.text = text
        self.recognize_error = recognize_error

    def recognize_google(self, audio: str, language: str) -> str:
        """Mocks the actual recognition call."""
        if self.recognize_error:
            raise self.recognize_error
        return self.text


class TestSpeechRecognition(unittest.TestCase):
    """Tests for the SpeechRecognition class."""

    def test_successful_recognition(self) -> None:
        """Verify successful recognition returns the correct text."""
        recognizer = SpeechRecognition(
            recognizer_factory=lambda: FakeRecognizer(text="open notepad")
        )

        result = recognizer.recognize("fake_audio_data")

        self.assertTrue(result.success)
        self.assertEqual(result.text, "open notepad")
        self.assertEqual(result.error, "")

    def test_no_audio_input(self) -> None:
        """Verify that None audio input results in a failure."""
        recognizer = SpeechRecognition()

        result = recognizer.recognize(None)

        self.assertFalse(result.success)
        self.assertEqual(result.text, "")
        self.assertEqual(result.error, "No audio was captured.")

    def test_recognition_library_not_available(self) -> None:
        """Verify failure when the speech_recognition library can't be imported."""
        # Simulate the factory failing because the import is missing
        recognizer = SpeechRecognition(
            recognizer_factory=lambda: (_ for _ in ()).throw(ImportError("No module"))
        )

        result = recognizer.recognize("fake_audio_data")

        self.assertFalse(result.success)
        self.assertEqual(result.error, "Speech recognition support is not available.")

    def test_inaudible_speech_returns_failure(self) -> None:
        """Verify that inaudible speech is handled gracefully."""
        # The real library raises UnknownValueError for this case.
        recognizer = SpeechRecognition(
            recognizer_factory=lambda: FakeRecognizer(recognize_error=ValueError())
        )

        result = recognizer.recognize("fake_audio_data")

        self.assertFalse(result.success)
        self.assertEqual(result.error, "No speech could be recognized.")

    def test_network_error_returns_failure(self) -> None:
        """Verify that a network or API error is handled."""
        # The real library raises RequestError for this case.
        recognizer = SpeechRecognition(
            recognizer_factory=lambda: FakeRecognizer(recognize_error=RuntimeError())
        )

        result = recognizer.recognize("fake_audio_data")

        self.assertFalse(result.success)
        self.assertEqual(result.error, "Speech recognition service is unavailable.")

    def test_timeout_error_returns_failure(self) -> None:
        """Verify that a timeout is handled."""
        recognizer = SpeechRecognition(
            recognizer_factory=lambda: FakeRecognizer(recognize_error=TimeoutError())
        )

        result = recognizer.recognize("fake_audio_data")

        self.assertFalse(result.success)
        self.assertEqual(result.error, "Speech recognition timed out.")

    def test_other_exception_returns_failure(self) -> None:
        """Verify that any other unexpected exception is caught."""
        recognizer = SpeechRecognition(
            recognizer_factory=lambda: FakeRecognizer(recognize_error=Exception("Boom!"))
        )

        result = recognizer.recognize("fake_audio_data")

        self.assertFalse(result.success)
        self.assertEqual(result.error, "Speech recognition failed.")

    def test_empty_recognized_text_returns_failure(self) -> None:
        """Verify that an empty string from the API is treated as a failure."""
        recognizer = SpeechRecognition(
            recognizer_factory=lambda: FakeRecognizer(text="   ")  # Whitespace only
        )

        result = recognizer.recognize("fake_audio_data")

        self.assertFalse(result.success)
        self.assertEqual(result.error, "No speech could be recognized.")

    def test_result_is_dataclass(self) -> None:
        """Verify the return type is the expected dataclass."""
        recognizer = SpeechRecognition(
            recognizer_factory=lambda: FakeRecognizer()
        )
        result = recognizer.recognize("fake_audio_data")
        self.assertIsInstance(result, SpeechRecognitionResult)


if __name__ == "__main__":
    unittest.main()