"""
dev_tests/test_microphone_service.py

Unit tests for the WakeWordService, focusing on its interaction with
the microphone stream and its lifecycle management.
"""

import unittest
from unittest.mock import MagicMock, patch

from services.base_service import ServiceStatus
from services.wake_word_service import WakeWordService


class TestMicrophoneService(unittest.TestCase):
    """Test cases for the WakeWordService."""

    @patch("voice.microphone_stream.MicrophoneStream")
    def setUp(self, mock_microphone_stream_class: MagicMock) -> None:
        """Set up each test with a new service and mocked stream."""
        self.mock_microphone_stream = mock_microphone_stream_class.return_value
        self.service = WakeWordService()

    def test_initialize(self) -> None:
        """Verify that initialize creates a MicrophoneStream instance."""
        self.assertIsNone(self.service._microphone_stream)
        self.service.initialize()
        self.assertIsNotNone(self.service._microphone_stream)
        self.assertIs(self.service._microphone_stream, self.mock_microphone_stream)

    def test_start(self) -> None:
        """Verify that start calls the stream's start method."""
        self.service.initialize()
        self.service.start()
        self.mock_microphone_stream.start.assert_called_once()

    def test_stop(self) -> None:
        """Verify that stop calls the stream's stop method."""
        self.service.initialize()
        self.service.start()
        self.service.stop()
        self.mock_microphone_stream.stop.assert_called_once()

    def test_shutdown(self) -> None:
        """Verify that shutdown calls the stream's shutdown method."""
        self.service.initialize()
        self.service.start()
        self.service.shutdown()
        self.mock_microphone_stream.shutdown.assert_called_once()

    def test_restart(self) -> None:
        """Verify that restart calls stop and then start."""
        self.service.initialize()
        self.service.start()

        # To test restart, we need to mock stop and start to check call order
        self.service.stop = MagicMock()
        self.service.start = MagicMock()

        self.service.restart()

        self.service.stop.assert_called_once()
        self.service.start.assert_called_once()

    @patch("voice.microphone_stream.MicrophoneStream")
    def test_initialization_failure(
        self, mock_microphone_stream_class: MagicMock
    ) -> None:
        """Test how the service handles a failure during initialization."""
        mock_microphone_stream_class.side_effect = Exception("Microphone not found")
        service = WakeWordService()
        with self.assertRaises(Exception):
            service.initialize()

    def test_start_failure(self) -> None:
        """Test how the service handles a failure during start."""
        self.mock_microphone_stream.start.side_effect = Exception("Failed to start stream")
        self.service.initialize()
        with self.assertRaises(Exception):
            self.service.start()


if __name__ == "__main__":
    unittest.main()
