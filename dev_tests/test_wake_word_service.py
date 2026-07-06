"""
dev_tests/test_wake_word_service.py

Unit tests for the WakeWordService.
"""

import unittest
from unittest.mock import MagicMock, patch

from services.base_service import ServiceStatus
from services.service_manager import ServiceManager
from services.wake_word_service import WakeWordService


class TestWakeWordServiceLifecycle(unittest.TestCase):
    """Tests the service lifecycle of WakeWordService."""

    def setUp(self) -> None:
        """Set up the test case."""
        self.service = WakeWordService()
        self.manager = ServiceManager()
        self.manager.register(self.service.name, self.service)

    def test_initial_status_is_stopped(self) -> None:
        """Verify the service starts in the STOPPED state."""
        self.assertEqual(self.service.status, ServiceStatus.STOPPED)

    @patch("services.wake_word_service.MicrophoneStream")
    def test_start_transitions_to_running(self, mock_microphone_stream_class: MagicMock) -> None:
        """Verify start() moves the service to RUNNING."""
        mock_microphone_stream = mock_microphone_stream_class.return_value
        self.manager.initialize_all()
        self.manager.start_all()
        self.assertEqual(self.service.status, ServiceStatus.RUNNING)
        mock_microphone_stream.start.assert_called_once()
        self.manager.stop_all()

    @patch("services.wake_word_service.MicrophoneStream")
    def test_stop_transitions_to_stopped(self, mock_microphone_stream_class: MagicMock) -> None:
        """Verify stop() moves the service to STOPPED."""
        mock_microphone_stream = mock_microphone_stream_class.return_value
        self.manager.initialize_all()
        self.manager.start_all()
        self.manager.stop_all()
        self.assertEqual(self.service.status, ServiceStatus.STOPPED)
        mock_microphone_stream.stop.assert_called_once()

    @patch("services.wake_word_service.MicrophoneStream")
    def test_restart_stops_and_starts(self, mock_microphone_stream_class: MagicMock) -> None:
        """Verify restart() calls stop and then start."""
        mock_microphone_stream = mock_microphone_stream_class.return_value
        self.manager.initialize_all()
        self.manager.start_all()
        mock_microphone_stream.start.assert_called_once()

        self.manager.restart(self.service.name)
        self.assertEqual(self.service.status, ServiceStatus.RUNNING)
        mock_microphone_stream.stop.assert_called_once()
        self.assertEqual(mock_microphone_stream.start.call_count, 2)

        self.manager.stop_all()

    @patch("services.wake_word_service.MicrophoneStream")
    def test_shutdown_stops_the_service(self, mock_microphone_stream_class: MagicMock) -> None:
        """Verify shutdown() stops the service."""
        mock_microphone_stream = mock_microphone_stream_class.return_value
        self.manager.initialize_all()
        self.manager.start_all()
        self.manager.shutdown_all()
        mock_microphone_stream.shutdown.assert_called_once()

    def test_initialization_failure_sets_status_to_failed(self) -> None:
        """Verify that a failure during initialization sets the service status to FAILED."""
        # We need a new mock for this test to simulate the side effect on the constructor
        with patch("services.wake_word_service.MicrophoneStream") as mock_stream:
            mock_stream.side_effect = Exception("Initialization failed")
            service = WakeWordService()
            manager = ServiceManager()
            manager.register(service.name, service)

            manager.initialize_all()
            self.assertEqual(service.status, ServiceStatus.FAILED)


if __name__ == "__main__":
    unittest.main()
