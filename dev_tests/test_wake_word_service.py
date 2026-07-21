"""
dev_tests/test_wake_word_service.py

Unit tests for the WakeWordService.
"""

import unittest
from unittest.mock import MagicMock, patch
import threading

from services.base_service import ServiceStatus
from services.service_manager import ServiceManager
from services.wake_word_service import WakeWordService


class TestWakeWordServiceLifecycle(unittest.TestCase):
    """Tests the service lifecycle of WakeWordService."""

    def setUp(self) -> None:
        """Set up the test case."""
        self.wake_word_event = threading.Event()
        self.mock_mic_stream = MagicMock()
        self.service = WakeWordService(
            wake_word_detected_event=self.wake_word_event,
            microphone_stream=self.mock_mic_stream,
        )
        self.manager = ServiceManager()
        self.manager.register(self.service.name, self.service)

    def test_initial_status_is_stopped(self) -> None:
        """Verify the service starts in the STOPPED state."""
        self.assertEqual(self.service.status, ServiceStatus.STOPPED)

    def test_start_sets_consumer(self) -> None:
        """Verify start() sets the audio consumer on the MicrophoneStream."""
        self.manager.initialize_all()
        self.manager.start_all()
        self.assertEqual(self.service.status, ServiceStatus.RUNNING)
        self.mock_mic_stream.set_consumer.assert_called_once()
        self.manager.stop_all()

    def test_stop_clears_consumer(self) -> None:
        """Verify stop() clears the audio consumer."""
        self.manager.initialize_all()
        self.manager.start_all()
        self.manager.stop_all()
        self.assertEqual(self.service.status, ServiceStatus.STOPPED)
        self.mock_mic_stream.set_consumer.assert_called_with(None)

    def test_restart_sets_consumer_twice(self) -> None:
        """Verify restart() clears consumer, then re-sets it."""
        self.manager.initialize_all()
        self.manager.start_all()
        self.mock_mic_stream.set_consumer.assert_called_once()

        self.manager.restart(self.service.name)
        self.assertEqual(self.service.status, ServiceStatus.RUNNING)
        # stop() + start() = 2 more calls beyond the initial start()
        self.assertEqual(self.mock_mic_stream.set_consumer.call_count, 3)

        self.manager.stop_all()

    def test_shutdown_clears_consumer(self) -> None:
        """Verify shutdown() clears the consumer but does not close the stream."""
        self.manager.initialize_all()
        self.manager.start_all()
        self.manager.shutdown_all()
        self.mock_mic_stream.set_consumer.assert_called_with(None)
        self.mock_mic_stream.shutdown.assert_not_called()

    def test_initialization_failure_sets_status_to_failed(self) -> None:
        """Verify that a failure during initialization sets the service status to FAILED."""
        import voice.wakeword
        original = voice.wakeword.WakeWordDetector
        voice.wakeword.WakeWordDetector = MagicMock(
            side_effect=Exception("Initialization failed"),
        )
        try:
            service = WakeWordService(
                wake_word_detected_event=threading.Event(),
                microphone_stream=MagicMock(),
            )
            manager = ServiceManager()
            manager.register(service.name, service)

            manager.initialize_all()
            self.assertEqual(service.status, ServiceStatus.FAILED)
        finally:
            voice.wakeword.WakeWordDetector = original


if __name__ == "__main__":
    unittest.main()
