"""
dev_tests/test_microphone_service.py

Unit tests for the WakeWordService, focusing on its interaction with
the microphone stream and its lifecycle management.
"""

import unittest
from unittest.mock import MagicMock, patch
import threading

from services.base_service import ServiceStatus
from services.wake_word_service import WakeWordService


class TestMicrophoneService(unittest.TestCase):
    """Test cases for the WakeWordService."""

    def setUp(self) -> None:
        """Set up each test with a new service instance."""
        self.service = WakeWordService(wake_word_detected_event=threading.Event())

    @patch("services.wake_word_service.MicrophoneStream")
    def test_initialize(self, mock_microphone_stream_class: MagicMock) -> None:
        """Verify that initialize creates a MicrophoneStream instance."""
        self.assertIsNone(self.service._microphone_stream)
        self.service.initialize()
        self.assertIsNotNone(self.service._microphone_stream)
        mock_microphone_stream_class.assert_called_once()

    @patch("services.wake_word_service.MicrophoneStream")
    def test_start(self, mock_microphone_stream_class: MagicMock) -> None:
        """Verify that start calls the stream's start method."""
        mock_microphone_stream = mock_microphone_stream_class.return_value
        self.service.initialize()
        self.service.start()
        mock_microphone_stream.start.assert_called_once()

    @patch("services.wake_word_service.MicrophoneStream")
    def test_stop(self, mock_microphone_stream_class: MagicMock) -> None:
        """Verify that stop calls the stream's stop method."""
        mock_microphone_stream = mock_microphone_stream_class.return_value
        self.service.initialize()
        self.service.start()
        self.service.stop()
        mock_microphone_stream.stop.assert_called_once()

    @patch("services.wake_word_service.MicrophoneStream")
    def test_shutdown(self, mock_microphone_stream_class: MagicMock) -> None:
        """Verify that shutdown calls the stream's shutdown method."""
        mock_microphone_stream = mock_microphone_stream_class.return_value
        self.service.initialize()
        self.service.start()
        self.service.shutdown()
        mock_microphone_stream.shutdown.assert_called_once()

    def test_restart(self) -> None:
        """Verify that restart calls stop and then start."""
        
        # To test restart, we need to mock stop and start to check call order
        self.service.stop = MagicMock()
        self.service.start = MagicMock()

        self.service.restart()

        self.service.stop.assert_called_once()
        self.service.start.assert_called_once()

    @patch("services.wake_word_service.MicrophoneStream")
    def test_initialization_does_not_fail(
        self, mock_microphone_stream_class: MagicMock
    ) -> None:
        """Test that service initialization does not fail if microphone is not found."""
        mock_microphone_stream_class.side_effect = Exception("Microphone not found")
        try:
            self.service.initialize()
        except Exception:
            self.fail("initialize() raised an exception unexpectedly.")

    @patch("services.wake_word_service.MicrophoneStream")
    def test_start_failure(self, mock_microphone_stream_class: MagicMock) -> None:
        """Test how the service handles a failure during start."""
        mock_microphone_stream = mock_microphone_stream_class.return_value
        mock_microphone_stream.start.side_effect = Exception("Failed to start stream")
        self.service.initialize()
        with self.assertRaises(Exception):
            self.service.start()


if __name__ == "__main__":
    unittest.main()
