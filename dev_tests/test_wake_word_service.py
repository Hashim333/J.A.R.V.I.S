"""
dev_tests/test_wake_word_service.py

Unit tests for the WakeWordService adapter under VOICE-PIPELINE-004.

JARVIS now operates WITHOUT a wake word (direct listening while IDLE), so the
wake detector stays disabled: ``start`` / ``reset_for_wake`` are no-ops and
Vosk never loads.  ``stop`` / ``shutdown`` remain defensive pause calls.
"""

import unittest
import threading
from unittest.mock import MagicMock

from services.base_service import ServiceStatus
from services.service_manager import ServiceManager
from services.wake_word_service import WakeWordService


class TestWakeWordServiceLifecycle(unittest.TestCase):
    """Tests the service lifecycle of WakeWordService."""

    def setUp(self) -> None:
        """Set up the test case with a mock session attached."""
        self.wake_word_event = threading.Event()
        self.mock_mic_stream = MagicMock()
        self.mock_session = MagicMock()
        self.service = WakeWordService(
            wake_word_detected_event=self.wake_word_event,
            microphone_stream=self.mock_mic_stream,
        )
        self.service.set_session(self.mock_session)
        self.manager = ServiceManager()
        self.manager.register(self.service.name, self.service)

    def test_initial_status_is_stopped(self) -> None:
        """Verify the service starts in the STOPPED state."""
        self.assertEqual(self.service.status, ServiceStatus.STOPPED)

    def test_initialize_is_noop_and_does_not_arm_detection(self) -> None:
        """initialize() succeeds and never arms the wake detector."""
        self.manager.initialize_all()
        self.manager.start_all()
        self.assertEqual(self.service.status, ServiceStatus.RUNNING)
        self.mock_session.start_wake_detection.assert_not_called()
        self.mock_mic_stream.set_consumer.assert_not_called()
        self.manager.stop_all()

    def test_start_is_noop_under_direct_listening(self) -> None:
        """VOICE-PIPELINE-004: start() must NOT arm wake detection."""
        self.service.start()
        self.mock_session.start_wake_detection.assert_not_called()
        self.mock_session.reset_wake.assert_not_called()
        self.mock_mic_stream.set_consumer.assert_not_called()

    def test_reset_for_wake_is_inert(self) -> None:
        """VOICE-PIPELINE-004: reset_for_wake() must not re-arm detection."""
        self.service._command_audio = object()
        self.service.reset_for_wake()
        self.mock_session.start_wake_detection.assert_not_called()
        self.mock_session.reset_wake.assert_not_called()
        self.assertIsNone(self.service._command_audio)

    def test_stop_pauses_detection_defensively(self) -> None:
        """stop() remains a defensive pause call on the session."""
        self.service.stop()
        self.mock_session.stop_wake_detection.assert_called_once()

    def test_shutdown_pauses_detection_without_closing_stream(self) -> None:
        """shutdown() pauses detection but never closes the shared stream."""
        self.service.shutdown()
        self.mock_session.stop_wake_detection.assert_called_once()
        self.mock_mic_stream.shutdown.assert_not_called()

    def test_get_command_audio_returns_stored_audio(self) -> None:
        """get_command_audio() returns the last captured wake audio."""
        class _Audio:
            frame_data = b"x" * 16

        self.service._on_wake_word(_Audio())
        self.assertTrue(self.wake_word_event.is_set())
        self.assertIsInstance(self.service.get_command_audio(), _Audio)


if __name__ == "__main__":
    unittest.main()
