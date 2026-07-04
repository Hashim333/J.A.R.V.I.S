"""
dev_tests/test_wake_word_service.py

Unit tests for the WakeWordService.
"""

import time
import unittest
from unittest.mock import patch

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

    def test_start_transitions_to_running(self) -> None:
        """Verify start() moves the service to RUNNING."""
        self.manager.start_all()
        self.assertEqual(self.service.status, ServiceStatus.RUNNING)
        self.assertIsNotNone(self.service._thread)
        self.assertTrue(self.service._thread.is_alive())
        self.manager.stop_all()

    def test_stop_transitions_to_stopped(self) -> None:
        """Verify stop() moves the service to STOPPED and joins the thread."""
        self.manager.start_all()
        thread = self.service._thread
        self.assertIsNotNone(thread)
        self.assertTrue(thread.is_alive())

        self.manager.stop_all()
        self.assertEqual(self.service.status, ServiceStatus.STOPPED)
        self.assertFalse(thread.is_alive())
        self.assertIsNone(self.service._thread)

    def test_multiple_starts_are_safe(self) -> None:
        """Verify calling start() multiple times is handled gracefully."""
        self.manager.start_all()
        first_thread = self.service._thread

        self.manager.start_all()  # Second start call
        second_thread = self.service._thread

        self.assertIs(first_thread, second_thread)
        self.assertTrue(first_thread.is_alive())
        self.manager.stop_all()

    def test_multiple_stops_are_safe(self) -> None:
        """Verify calling stop() multiple times is handled gracefully."""
        self.manager.start_all()
        self.manager.stop_all()
        self.assertEqual(self.service.status, ServiceStatus.STOPPED)

        try:
            self.manager.stop_all()  # Second stop call
        except Exception:
            self.fail("Calling stop() a second time raised an exception.")

    def test_restart_stops_and_starts_thread(self) -> None:
        """Verify restart() creates a new thread."""
        self.manager.start_all()
        first_thread = self.service._thread
        self.assertIsNotNone(first_thread)

        with patch.object(first_thread, 'join') as mock_join:
            self.manager.restart(self.service.name)
            mock_join.assert_called_once()

        self.assertEqual(self.service.status, ServiceStatus.RUNNING)
        second_thread = self.service._thread
        self.assertIsNotNone(second_thread)
        self.assertIsNot(first_thread, second_thread)
        self.assertTrue(second_thread.is_alive())

        self.manager.stop_all()

    def test_shutdown_stops_the_service(self) -> None:
        """Verify shutdown() stops the service thread."""
        self.manager.start_all()
        thread = self.service._thread
        self.assertTrue(thread.is_alive())

        self.manager.shutdown_all()
        self.assertFalse(thread.is_alive())


if __name__ == "__main__":
    unittest.main()