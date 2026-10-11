"""
dev_tests/test_watchdog_fake_clock.py

Unit test for the state-change watchdog using a fake clock.
No sleeping, no real mic, no real TTS, no OS actions.
"""

from __future__ import annotations

import sys
import threading
import time
import unittest
from unittest.mock import MagicMock, patch, PropertyMock

# Add project root to path
sys.path.insert(0, r"C:\Users\muham\OneDrive\Desktop\JARVIS")

from services.conversation_manager import ConversationManager, ConversationState
from services.conversation_owner import ConversationOwner


class FakeTime:
    """Fake time provider that can be controlled in tests."""
    def __init__(self, initial: float = 0.0):
        self._time = initial
        self._lock = threading.Lock()

    def monotonic(self) -> float:
        with self._lock:
            return self._time

    def advance(self, seconds: float) -> None:
        with self._lock:
            self._time += seconds

    def set(self, value: float) -> None:
        with self._lock:
            self._time = value


class TestWatchdogFakeClock(unittest.TestCase):
    """Test the state-change watchdog with a fake clock."""

    def setUp(self):
        """Set up mocks and fake time."""
        self.fake_time = FakeTime(1000.0)

        # Mock all external dependencies
        self.mock_bridge = MagicMock()
        self.mock_brain = MagicMock()
        self.mock_task_manager = MagicMock()
        self.mock_response_manager = MagicMock()
        self.mock_voice_engine = MagicMock()
        self.mock_wake_word_service = MagicMock()
        self.mock_microphone_stream = MagicMock()
        self.mock_duplex_session = MagicMock()
        self.mock_command_queue = MagicMock()
        self.mock_wake_word_detected = threading.Event()
        self.mock_watchdog_manager = MagicMock()
        self.mock_service_manager = MagicMock()
        self.mock_shutdown_in_progress = threading.Event()
        self.mock_shutdown_event = threading.Event()

        # Configure mocks
        self.mock_voice_engine.is_busy = False
        self.mock_voice_engine.is_speaking = False
        self.mock_voice_engine.queue_size = 0
        self.mock_voice_engine.speak = MagicMock(return_value=True)
        self.mock_voice_engine.interrupt = MagicMock()
        self.mock_voice_engine.cancel_all = MagicMock()
        self.mock_voice_engine.stop_barge_in = MagicMock()
        self.mock_voice_engine.start_barge_in = MagicMock()

        self.mock_duplex_session.is_capture_active = False
        self.mock_duplex_session.capture_command = MagicMock()
        self.mock_duplex_session.cancel_capture = MagicMock()
        self.mock_duplex_session.reset_capture_state = MagicMock()
        self.mock_duplex_session.capture_generation = 0

        self.mock_microphone_stream.is_running = True
        self.mock_microphone_stream.is_muted = False
        self.mock_microphone_stream.mute_owners = []
        self.mock_microphone_stream.consumer_is = MagicMock(return_value=True)
        self.mock_microphone_stream.set_consumer = MagicMock()
        self.mock_microphone_stream.unmute = MagicMock()
        self.mock_microphone_stream.shutdown = MagicMock()
        self.mock_microphone_stream.start = MagicMock()

        self.mock_wake_word_service.stop = MagicMock()
        self.mock_wake_word_service.reset_for_wake = MagicMock()
        self.mock_wake_word_service.set_session = MagicMock()

        # Mock conversation manager instead of real instance
        self.mock_conversation_manager = MagicMock()
        # Use PropertyMock for state so we can change it
        type(self.mock_conversation_manager).state = PropertyMock(return_value=ConversationState.IDLE)
        self.mock_conversation_manager.has_pending_confirmation = False
        self.mock_conversation_manager.is_expired = False
        self.mock_conversation_manager._activity_timeout = 30.0
        self.mock_conversation_manager.on_timeout = MagicMock()
        self.mock_conversation_manager.return_to_idle = MagicMock()
        self.mock_conversation_manager.on_wake_word = MagicMock()
        self.mock_conversation_manager.on_listening = MagicMock()
        self.mock_conversation_manager.on_command_received = MagicMock()
        self.mock_conversation_manager.transition_to_active = MagicMock()
        self.mock_conversation_manager.reset_activity = MagicMock()
        self.mock_conversation_manager.is_exit_command = MagicMock(return_value=False)
        self.mock_conversation_manager.request_confirmation = MagicMock()

        self.mock_task_manager.cancel_active = MagicMock()
        self.mock_task_manager.check_timeouts = MagicMock(return_value=[])
        self.mock_task_manager.create_task = MagicMock()
        self.mock_task_manager.start_task = MagicMock()
        self.mock_task_manager.register_cleanup = MagicMock()
        self.mock_task_manager.mark_success = MagicMock()
        self.mock_task_manager.mark_failed = MagicMock()

        self.mock_response_manager._voice_enabled = True
        self.mock_response_manager.console_text = MagicMock(return_value="Test response")
        self.mock_response_manager.voice_text = MagicMock(return_value="Test response")

        self.mock_brain.cancel_current = MagicMock()
        self.mock_brain.process = MagicMock(return_value=MagicMock(
            success=True, task_result=MagicMock(value="SUCCESS"),
            data={"intent": "test"}, needs_clarification=False
        ))
        self.mock_brain.resolve_context = MagicMock(return_value=MagicMock(
            success=True, task_result=MagicMock(value="SUCCESS"),
            data={"intent": "test"}, needs_clarification=False
        ))

        self.mock_service_manager.initialize_all = MagicMock(return_value={})
        self.mock_service_manager.start_all = MagicMock(return_value={})
        self.mock_service_manager.shutdown_all = MagicMock(return_value={})

        self.mock_watchdog_manager.add = MagicMock()
        self.mock_watchdog_manager.kick = MagicMock()
        self.mock_watchdog_manager.stop_all = MagicMock()

        # Patch time.monotonic to use our fake clock
        self.time_patcher = patch('time.monotonic', self.fake_time.monotonic)
        self.time_patcher.start()

        # Patch time.sleep to advance fake clock
        def fake_sleep(seconds):
            self.fake_time.advance(seconds)
        self.sleep_patcher = patch('time.sleep', side_effect=fake_sleep)
        self.sleep_patcher.start()

    def tearDown(self):
        self.time_patcher.stop()
        self.sleep_patcher.stop()

    def create_owner(self) -> ConversationOwner:
        """Create a ConversationOwner with mocked dependencies."""
        owner = ConversationOwner(
            conversation_manager=self.mock_conversation_manager,
            bridge=self.mock_bridge,
            brain=self.mock_brain,
            task_manager=self.mock_task_manager,
            response_manager=self.mock_response_manager,
            voice_engine=self.mock_voice_engine,
            wake_word_service=self.mock_wake_word_service,
            microphone_stream=self.mock_microphone_stream,
            duplex_session=self.mock_duplex_session,
            command_queue=self.mock_command_queue,
            wake_word_detected=self.mock_wake_word_detected,
            watchdog_manager=self.mock_watchdog_manager,
            service_manager=self.mock_service_manager,
            shutdown_in_progress=self.mock_shutdown_in_progress,
            shutdown_event=self.mock_shutdown_event,
            wake_word_enabled=False,  # Direct listening mode
        )
        return owner

    def test_watchdog_speaking_timeout(self):
        """Test that SPEAKING state times out after 30s and interrupts TTS."""
        owner = self.create_owner()

        # Set state to SPEAKING via PropertyMock
        type(self.mock_conversation_manager).state = PropertyMock(return_value=ConversationState.SPEAKING)
        owner._last_state_change = self.fake_time.monotonic()

        # Advance time by 31 seconds (past 30s limit)
        self.fake_time.advance(31.0)

        # Call the watchdog callback
        owner._on_state_change_stall("test")

        # Verify TTS was interrupted
        self.mock_voice_engine.interrupt.assert_called()
        self.mock_voice_engine.stop_barge_in.assert_called()

        # Verify watchdog was re-armed
        self.mock_watchdog_manager.kick.assert_called_with("state_change")

    def test_watchdog_thinking_timeout(self):
        """Test that THINKING state times out after 60s and cancels task."""
        owner = self.create_owner()

        # Set state to THINKING via PropertyMock
        type(self.mock_conversation_manager).state = PropertyMock(return_value=ConversationState.THINKING)
        owner._last_state_change = self.fake_time.monotonic()

        # Advance time by 61 seconds (past 60s limit)
        self.fake_time.advance(61.0)

        # Call the watchdog callback
        owner._on_state_change_stall("test")

        # Verify task was cancelled
        self.mock_task_manager.cancel_active.assert_called()
        self.mock_brain.cancel_current.assert_called()
        self.mock_duplex_session.cancel_capture.assert_called()

        # Verify watchdog was re-armed
        self.mock_watchdog_manager.kick.assert_called_with("state_change")

    def test_watchdog_waiting_confirmation_exempt(self):
        """Test that WAITING_CONFIRMATION state is exempt from timeout."""
        owner = self.create_owner()

        # Set state to WAITING_CONFIRMATION
        type(self.mock_conversation_manager).state = PropertyMock(return_value=ConversationState.WAITING_CONFIRMATION)
        owner._last_state_change = self.fake_time.monotonic()

        # Advance time by 100 seconds (well past any limit)
        self.fake_time.advance(100.0)

        # Call the watchdog callback
        owner._on_state_change_stall("test")

        # Verify NO recovery action was taken (exempt)
        self.mock_voice_engine.interrupt.assert_not_called()
        self.mock_task_manager.cancel_active.assert_not_called()
        self.mock_conversation_manager.return_to_idle.assert_not_called()

        # Verify watchdog was re-armed (just to keep it alive)
        self.mock_watchdog_manager.kick.assert_called_with("state_change")

    def test_watchdog_listening_no_capture_restarts(self):
        """Test that LISTENING with no active capture re-arms the capture path."""
        owner = self.create_owner()

        # Set state to LISTENING
        type(self.mock_conversation_manager).state = PropertyMock(return_value=ConversationState.LISTENING)
        owner._last_state_change = self.fake_time.monotonic()

        # No active capture
        self.mock_duplex_session.is_capture_active = False

        # Advance time by 21 seconds (past 20s limit)
        self.fake_time.advance(21.0)

        # Call the watchdog callback
        owner._on_state_change_stall("test")

        # Verify _ensure_listening_ready was called
        # (We can't directly assert on private method, but we can check
        # that the microphone stream was checked/unmuted)
        self.mock_microphone_stream.unmute.assert_called()

        # Verify watchdog was re-armed
        self.mock_watchdog_manager.kick.assert_called_with("state_change")

    def test_watchdog_listening_with_capture_cancels_stuck(self):
        """Test that LISTENING with active capture cancels the stuck capture."""
        owner = self.create_owner()

        # Set state to LISTENING via PropertyMock
        type(self.mock_conversation_manager).state = PropertyMock(return_value=ConversationState.LISTENING)
        owner._last_state_change = self.fake_time.monotonic()

        # Active capture is stuck
        self.mock_duplex_session.is_capture_active = True

        # Advance time by 21 seconds (past 20s limit)
        self.fake_time.advance(21.0)

        # Call the watchdog callback
        owner._on_state_change_stall("test")

        # Verify stuck capture was cancelled
        self.mock_duplex_session.cancel_capture.assert_called()

        # Verify watchdog was re-armed
        self.mock_watchdog_manager.kick.assert_called_with("state_change")

    def test_watchdog_idle_returns_to_idle(self):
        """Test that IDLE state returns to idle (no-op but logs)."""
        owner = self.create_owner()

        # Set state to IDLE
        type(self.mock_conversation_manager).state = PropertyMock(return_value=ConversationState.IDLE)
        owner._last_state_change = self.fake_time.monotonic()

        # Advance time by 21 seconds (past 20s default limit)
        self.fake_time.advance(21.0)

        # Call the watchdog callback
        owner._on_state_change_stall("test")

        # Verify return_to_idle was called
        self.mock_conversation_manager.return_to_idle.assert_called()

        # Verify bridge notifications
        self.mock_bridge.emit_passive.assert_called()
        self.mock_bridge.show_subtitle.assert_called()

        # Verify watchdog was re-armed
        self.mock_watchdog_manager.kick.assert_called_with("state_change")

    def test_watchdog_not_triggered_before_limit(self):
        """Test that watchdog does nothing if time hasn't exceeded limit."""
        owner = self.create_owner()

        # Set state to SPEAKING
        type(self.mock_conversation_manager).state = PropertyMock(return_value=ConversationState.SPEAKING)
        owner._last_state_change = self.fake_time.monotonic()

        # Advance time by only 10 seconds (under 30s limit)
        self.fake_time.advance(10.0)

        # Call the watchdog callback
        owner._on_state_change_stall("test")

        # Verify NO recovery action was taken
        self.mock_voice_engine.interrupt.assert_not_called()
        self.mock_task_manager.cancel_active.assert_not_called()

        # Verify watchdog was re-armed (to keep monitoring)
        self.mock_watchdog_manager.kick.assert_called_with("state_change")

    def test_watchdog_thread_stack_dump(self):
        """Test that thread stack dump is attempted."""
        owner = self.create_owner()

        # Set state to IDLE
        type(self.mock_conversation_manager).state = PropertyMock(return_value=ConversationState.IDLE)
        owner._last_state_change = self.fake_time.monotonic()

        # Advance time by 21 seconds
        self.fake_time.advance(21.0)

        # Call the watchdog callback
        owner._on_state_change_stall("test")

        # Just verify it doesn't crash - the stack dump is logged
        # We can't easily test the log output, but we verify no exception
        self.assertTrue(True)


if __name__ == "__main__":
    unittest.main(verbosity=2)
