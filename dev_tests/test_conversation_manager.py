"""
dev_tests/test_conversation_manager.py

Unit tests for services/conversation_manager.py.

Covers the full state machine:
    - Initial state is STANDBY
    - transition_to_active() moves to ACTIVE_CONVERSATION
    - transition_to_standby() moves back to STANDBY
    - Idempotent transitions (no-op when already in target state)
    - is_expired / remaining_time timeout behaviour
    - reset_activity() extends the timeout
    - is_sleep_command() recognises all sleep phrases
    - is_sleep_command() is case-insensitive and ignores whitespace
    - Non-sleep commands are rejected
    - Wake word service is stopped on activation, reset on standby
    - Listener service integration
"""

from __future__ import annotations

import time
import unittest
from unittest.mock import MagicMock

from services.conversation_manager import ConversationManager, ConversationState
from services.listener_service import ListenerService
from services.wake_word_service import WakeWordService


# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------

def _fake_wake_word_service() -> MagicMock:
    svc = MagicMock(spec=WakeWordService)
    svc.stop = MagicMock()
    svc.reset_for_wake = MagicMock()
    return svc


def _fake_listener_service() -> MagicMock:
    svc = MagicMock(spec=ListenerService)
    svc.listen_for_command = MagicMock()
    return svc


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestInitialState(unittest.TestCase):
    """ConversationManager starts in STANDBY."""

    def setUp(self) -> None:
        self.manager = ConversationManager(
            wake_word_service=_fake_wake_word_service(),
            listener_service=_fake_listener_service(),
        )

    def test_initial_state_is_standby(self) -> None:
        self.assertEqual(self.manager.state, ConversationState.STANDBY)

    def test_initial_is_expired_false(self) -> None:
        self.assertFalse(self.manager.is_expired)

    def test_initial_remaining_time_equals_timeout(self) -> None:
        self.assertEqual(self.manager.remaining_time, 30.0)

    def test_initial_not_expired_when_not_active(self) -> None:
        self.manager._state = ConversationState.STANDBY
        self.manager._last_activity = 0.0
        self.assertFalse(self.manager.is_expired)


class TestTransitions(unittest.TestCase):
    """State transitions are correct and idempotent."""

    def setUp(self) -> None:
        self.wake = _fake_wake_word_service()
        self.manager = ConversationManager(
            wake_word_service=self.wake,
            listener_service=_fake_listener_service(),
        )

    def test_transition_to_active_changes_state(self) -> None:
        self.manager.transition_to_active()
        self.assertEqual(self.manager.state, ConversationState.ACTIVE_CONVERSATION)

    def test_transition_to_active_stops_wake_word(self) -> None:
        self.manager.transition_to_active()
        self.wake.stop.assert_called_once()

    def test_transition_to_active_sets_last_activity(self) -> None:
        self.manager.transition_to_active()
        self.assertIsNotNone(self.manager._last_activity)

    def test_transition_to_active_is_idempotent(self) -> None:
        self.manager.transition_to_active()
        self.wake.stop.reset_mock()
        self.manager.transition_to_active()
        self.wake.stop.assert_not_called()

    def test_transition_to_standby_changes_state(self) -> None:
        self.manager.transition_to_active()
        self.manager.transition_to_standby(reason="test")
        self.assertEqual(self.manager.state, ConversationState.STANDBY)

    def test_transition_to_standby_resets_wake_word(self) -> None:
        self.manager.transition_to_active()
        self.manager.transition_to_standby(reason="test")
        self.wake.reset_for_wake.assert_called_once()

    def test_transition_to_standby_clears_last_activity(self) -> None:
        self.manager.transition_to_active()
        self.manager.transition_to_standby(reason="test")
        self.assertIsNone(self.manager._last_activity)

    def test_transition_to_standby_is_idempotent(self) -> None:
        self.manager.transition_to_standby(reason="test")
        self.wake.reset_for_wake.assert_not_called()

    def test_full_cycle(self) -> None:
        """STANDBY -> ACTIVE -> STANDBY cycle works."""
        self.assertEqual(self.manager.state, ConversationState.STANDBY)
        self.manager.transition_to_active()
        self.assertEqual(self.manager.state, ConversationState.ACTIVE_CONVERSATION)
        self.manager.transition_to_standby(reason="sleep")
        self.assertEqual(self.manager.state, ConversationState.STANDBY)


class TestTimeout(unittest.TestCase):
    """Inactivity timeout works correctly."""

    def setUp(self) -> None:
        self.manager = ConversationManager(
            wake_word_service=_fake_wake_word_service(),
            listener_service=_fake_listener_service(),
            activity_timeout=0.1,
        )
        self.manager.transition_to_active()

    def test_not_expired_immediately_after_activity(self) -> None:
        self.assertFalse(self.manager.is_expired)

    def test_expired_after_timeout(self) -> None:
        time.sleep(0.15)
        self.assertTrue(self.manager.is_expired)

    def test_remaining_time_decreases(self) -> None:
        initial = self.manager.remaining_time
        time.sleep(0.05)
        self.assertLess(self.manager.remaining_time, initial)

    def test_reset_activity_extends_timeout(self) -> None:
        time.sleep(0.08)
        self.manager.reset_activity()
        time.sleep(0.08)
        self.assertFalse(self.manager.is_expired)

    def test_expired_after_reset_and_long_wait(self) -> None:
        self.manager.reset_activity()
        time.sleep(0.15)
        self.assertTrue(self.manager.is_expired)

    def test_remaining_time_zero_when_expired(self) -> None:
        time.sleep(0.15)
        self.assertEqual(self.manager.remaining_time, 0.0)

    def test_custom_timeout(self) -> None:
        mgr = ConversationManager(
            wake_word_service=_fake_wake_word_service(),
            listener_service=_fake_listener_service(),
            activity_timeout=5.0,
        )
        mgr.transition_to_active()
        self.assertEqual(mgr.remaining_time, 5.0)


class TestSleepCommands(unittest.TestCase):
    """Sleep command detection works correctly."""

    def test_go_to_sleep(self) -> None:
        self.assertTrue(ConversationManager.is_sleep_command("go to sleep"))

    def test_sleep(self) -> None:
        self.assertTrue(ConversationManager.is_sleep_command("sleep"))

    def test_stop_listening(self) -> None:
        self.assertTrue(ConversationManager.is_sleep_command("stop listening"))

    def test_stand_by(self) -> None:
        self.assertTrue(ConversationManager.is_sleep_command("stand by"))

    def test_goodbye(self) -> None:
        self.assertTrue(ConversationManager.is_sleep_command("goodbye"))

    def test_exit_conversation(self) -> None:
        self.assertTrue(ConversationManager.is_sleep_command("exit conversation"))

    def test_case_insensitive(self) -> None:
        self.assertTrue(ConversationManager.is_sleep_command("GO TO SLEEP"))
        self.assertTrue(ConversationManager.is_sleep_command("Sleep"))
        self.assertTrue(ConversationManager.is_sleep_command("Stop Listening"))

    def test_whitespace_tolerant(self) -> None:
        self.assertTrue(ConversationManager.is_sleep_command("  go to sleep  "))
        self.assertTrue(ConversationManager.is_sleep_command("\tstop listening\n"))

    def test_non_sleep_commands_rejected(self) -> None:
        self.assertFalse(ConversationManager.is_sleep_command("open chrome"))
        self.assertFalse(ConversationManager.is_sleep_command("close notepad"))
        self.assertFalse(ConversationManager.is_sleep_command("what time is it"))
        self.assertFalse(ConversationManager.is_sleep_command(""))
        self.assertFalse(ConversationManager.is_sleep_command("sleepy"))
        self.assertFalse(ConversationManager.is_sleep_command("going to sleep"))


class TestLifecycle(unittest.TestCase):
    """End-to-end conversation lifecycle scenarios."""

    def setUp(self) -> None:
        self.wake = _fake_wake_word_service()
        self.manager = ConversationManager(
            wake_word_service=self.wake,
            listener_service=_fake_listener_service(),
            activity_timeout=30.0,
        )

    def test_text_command_activates_conversation(self) -> None:
        """Simulate: user types 'open chrome' → system enters conversation mode."""
        self.assertEqual(self.manager.state, ConversationState.STANDBY)
        self.manager.transition_to_active()
        self.assertEqual(self.manager.state, ConversationState.ACTIVE_CONVERSATION)

    def test_multiple_commands_in_conversation(self) -> None:
        """Simulate: open chrome → open calculator → open notepad."""
        self.manager.transition_to_active()
        self.manager.reset_activity()
        self.manager.reset_activity()
        self.manager.reset_activity()
        self.assertEqual(self.manager.state, ConversationState.ACTIVE_CONVERSATION)

    def test_sleep_command_in_conversation(self) -> None:
        """Simulate: user says 'go to sleep' while in conversation."""
        self.manager.transition_to_active()
        self.assertEqual(self.manager.state, ConversationState.ACTIVE_CONVERSATION)
        self.manager.transition_to_standby(reason="sleep command")
        self.assertEqual(self.manager.state, ConversationState.STANDBY)

    def test_timeout_returns_to_standby(self) -> None:
        """Simulate: 30s of inactivity returns to STANDBY."""
        mgr = ConversationManager(
            wake_word_service=_fake_wake_word_service(),
            listener_service=_fake_listener_service(),
            activity_timeout=0.05,
        )
        mgr.transition_to_active()
        self.assertEqual(mgr.state, ConversationState.ACTIVE_CONVERSATION)
        time.sleep(0.1)
        self.assertTrue(mgr.is_expired)
        mgr.transition_to_standby(reason="timeout")
        self.assertEqual(mgr.state, ConversationState.STANDBY)

    def test_wake_word_service_stopped_in_active(self) -> None:
        """Wake word service is stopped when entering active conversation."""
        self.wake.stop.assert_not_called()
        self.manager.transition_to_active()
        self.wake.stop.assert_called_once()

    def test_wake_word_service_reset_on_standby(self) -> None:
        """Wake word service is reset when returning to standby."""
        self.manager.transition_to_active()
        self.manager.transition_to_standby(reason="test")
        self.wake.reset_for_wake.assert_called_once()


if __name__ == "__main__":
    unittest.main(verbosity=2)
