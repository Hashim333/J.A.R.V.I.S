"""
dev_tests/test_microphone_service.py

Unit tests for the WakeWordService, focusing on its interaction with
the microphone stream and its lifecycle management.
"""

import unittest
from unittest.mock import MagicMock
import threading

from services.base_service import ServiceStatus
from services.wake_word_service import WakeWordService


class TestMicrophoneService(unittest.TestCase):
    """Test cases for the WakeWordService."""

    def setUp(self) -> None:
        """Set up each test with a new service instance."""
        self.mock_mic_stream = MagicMock()
        self.service = WakeWordService(
            wake_word_detected_event=threading.Event(),
            microphone_stream=self.mock_mic_stream,
        )

    def test_initialize(self) -> None:
        """Verify that initialize creates a WakeWordDetector."""
        self.assertIsNone(self.service._wake_word_detector)
        self.service.initialize()
        self.assertIsNotNone(self.service._wake_word_detector)

    def test_start(self) -> None:
        """Verify that start calls set_consumer on the stream."""
        self.service.initialize()
        self.service.start()
        self.mock_mic_stream.set_consumer.assert_called_once()

    def test_stop(self) -> None:
        """Verify that stop calls set_consumer(None) on the stream."""
        self.service.initialize()
        self.service.start()
        self.service.stop()
        self.mock_mic_stream.set_consumer.assert_called_with(None)

    def test_shutdown(self) -> None:
        """Verify that shutdown calls set_consumer(None) but does NOT close the stream."""
        self.service.initialize()
        self.service.start()
        self.service.shutdown()
        self.mock_mic_stream.set_consumer.assert_called_with(None)
        self.mock_mic_stream.shutdown.assert_not_called()

    def test_restart(self) -> None:
        """Verify that restart calls stop and then start."""
        self.service.stop = MagicMock()
        self.service.start = MagicMock()

        self.service.restart()

        self.service.stop.assert_called_once()
        self.service.start.assert_called_once()

    def test_initialization_does_not_fail_on_mic_not_found(self) -> None:
        """Test that service initialization does not fail if microphone is not found."""
        import voice.wakeword
        original = voice.wakeword.WakeWordDetector
        voice.wakeword.WakeWordDetector = MagicMock(
            side_effect=Exception("Microphone not found"),
        )
        try:
            try:
                self.service.initialize()
            except Exception:
                self.fail("initialize() raised an exception unexpectedly.")
        finally:
            voice.wakeword.WakeWordDetector = original


if __name__ == "__main__":
    unittest.main()
