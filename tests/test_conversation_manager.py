from __future__ import annotations

import time
from unittest import TestCase

from services.conversation_manager import ConversationManager, ConversationState, is_exit_command


class TestConversationStateEnum(TestCase):
    def test_all_states_defined(self) -> None:
        expected = {
            "STANDBY", "IDLE", "WAKE_DETECTED", "LISTENING", "THINKING", "SPEAKING",
            "WAITING_CONFIRMATION", "EXECUTING", "ACTIVE_CONVERSATION",
            "TIMEOUT", "RETURN_TO_IDLE",
        }
        actual = {s.value for s in ConversationState}
        self.assertEqual(expected, actual)


class TestIsExitCommand(TestCase):
    def test_exit_conversation(self) -> None:
        self.assertTrue(is_exit_command("exit conversation"))

    def test_stop_listening(self) -> None:
        self.assertTrue(is_exit_command("stop listening"))

    def test_thank_you_goodbye(self) -> None:
        self.assertTrue(is_exit_command("thank you goodbye"))

    def test_sleep(self) -> None:
        self.assertTrue(is_exit_command("sleep"))

    def test_go_idle(self) -> None:
        self.assertTrue(is_exit_command("go idle"))

    def test_never_mind(self) -> None:
        self.assertTrue(is_exit_command("never mind"))

    def test_regular_command_not_exit(self) -> None:
        self.assertFalse(is_exit_command("open chrome"))

    def test_empty_not_exit(self) -> None:
        self.assertFalse(is_exit_command(""))


class TestConversationManager(TestCase):
    def setUp(self) -> None:
        self.cm = ConversationManager(activity_timeout=30.0, confirmation_timeout=10.0)

    def test_initial_state_is_standby(self) -> None:
        self.assertEqual(self.cm.state, ConversationState.STANDBY)

    def test_backend_ready_transitions_to_idle(self) -> None:
        self.cm.return_to_idle("backend ready")
        self.assertEqual(self.cm.state, ConversationState.IDLE)

    def test_wake_word_transition(self) -> None:
        self.cm.on_wake_word()
        self.assertEqual(self.cm.state, ConversationState.WAKE_DETECTED)

    def test_command_received_transition(self) -> None:
        self.cm.on_command_received()
        self.assertEqual(self.cm.state, ConversationState.THINKING)

    def test_speaking_transition(self) -> None:
        self.cm.on_speaking()
        self.assertEqual(self.cm.state, ConversationState.SPEAKING)

    def test_executing_transition(self) -> None:
        self.cm.on_executing()
        self.assertEqual(self.cm.state, ConversationState.EXECUTING)

    def test_enter_active_conversation(self) -> None:
        self.cm.enter_active_conversation()
        self.assertEqual(self.cm.state, ConversationState.ACTIVE_CONVERSATION)

    def test_return_to_idle(self) -> None:
        self.cm.enter_active_conversation()
        self.cm.return_to_idle("test")
        self.assertEqual(self.cm.state, ConversationState.IDLE)

    def test_timeout_transition(self) -> None:
        self.cm.enter_active_conversation()
        self.cm.on_timeout()
        self.assertEqual(self.cm.state, ConversationState.IDLE)

    def test_is_expired_false_when_idle(self) -> None:
        self.assertFalse(self.cm.is_expired)

    def test_is_expired_false_when_recent(self) -> None:
        self.cm.enter_active_conversation()
        self.assertFalse(self.cm.is_expired)

    def test_is_expired_true_after_timeout(self) -> None:
        cm = ConversationManager(activity_timeout=0.05)
        cm.enter_active_conversation()
        time.sleep(0.1)
        self.assertTrue(cm.is_expired)

    def test_reset_activity_prevents_timeout(self) -> None:
        cm = ConversationManager(activity_timeout=0.15)
        cm.enter_active_conversation()
        time.sleep(0.05)
        cm.reset_activity()
        time.sleep(0.05)
        self.assertFalse(cm.is_expired)

    def test_remaining_time_decreases(self) -> None:
        self.cm.enter_active_conversation()
        t1 = self.cm.remaining_time
        time.sleep(0.05)
        t2 = self.cm.remaining_time
        self.assertLess(t2, t1)

    def test_no_pending_confirmation_initially(self) -> None:
        self.assertFalse(self.cm.has_pending_confirmation)
        self.assertIsNone(self.cm.resume_pending())

    def test_request_confirmation_sets_pending(self) -> None:
        q = self.cm.request_confirmation("close_app", {"app_name": "notepad"}, "close notepad")
        self.assertTrue(self.cm.has_pending_confirmation)
        self.assertIn("close notepad", q)
        pending = self.cm.resume_pending()
        self.assertIsNotNone(pending)
        intent, entities, raw = pending
        self.assertEqual(intent, "close_app")
        self.assertEqual(entities["app_name"], "notepad")
        self.assertEqual(raw, "close notepad")

    def test_clear_on_return_to_idle(self) -> None:
        self.cm.request_confirmation("close_app", {}, "close")
        self.assertTrue(self.cm.has_pending_confirmation)
        self.cm.return_to_idle("test")
        self.assertFalse(self.cm.has_pending_confirmation)

    def test_classify_affirmative(self) -> None:
        self.assertEqual(self.cm.classify_confirmation("yes"), "affirmative")

    def test_classify_negative(self) -> None:
        self.assertEqual(self.cm.classify_confirmation("no"), "negative")

    def test_classify_unknown(self) -> None:
        self.assertEqual(self.cm.classify_confirmation("maybe"), "unknown")

    def test_exit_command_via_cm(self) -> None:
        self.assertTrue(self.cm.is_exit_command("stop listening"))
        self.assertFalse(self.cm.is_exit_command("open chrome"))

    def test_duplicate_state_does_not_log(self) -> None:
        self.cm.on_wake_word()
        self.cm.on_wake_word()
        self.assertEqual(self.cm.state, ConversationState.WAKE_DETECTED)


class _FakeWakeService:
    def __init__(self) -> None:
        self.reset_count = 0
        self.stop_count = 0

    def reset_for_wake(self) -> None:
        self.reset_count += 1

    def stop(self) -> None:
        self.stop_count += 1


class TestConversationManagerRearmWake(TestCase):
    """Leaving the engaged states always re-arms wake-word listening so the
    assistant can be woken again (Requirement #9)."""

    def _manager(self) -> tuple[ConversationManager, _FakeWakeService]:
        wake = _FakeWakeService()
        cm = ConversationManager(activity_timeout=30.0, wake_word_service=wake)
        return cm, wake

    def test_return_to_idle_rearms_wake(self) -> None:
        cm, wake = self._manager()
        cm.return_to_idle("test")
        self.assertEqual(cm.state, ConversationState.IDLE)
        self.assertGreaterEqual(wake.reset_count, 1)

    def test_on_timeout_rearms_wake(self) -> None:
        cm, wake = self._manager()
        cm.transition_to_active()
        cm.on_timeout()
        self.assertEqual(cm.state, ConversationState.IDLE)
        self.assertGreaterEqual(wake.reset_count, 1)

    def test_transition_to_active_stops_wake(self) -> None:
        cm, wake = self._manager()
        cm.transition_to_active()
        self.assertEqual(wake.stop_count, 1)

    def test_transition_to_active_touches_activity_each_call(self) -> None:
        cm, _ = self._manager()
        cm.transition_to_active()
        first = cm._last_activity
        time.sleep(0.05)
        cm.transition_to_active()
        second = cm._last_activity
        self.assertIsNotNone(first)
        self.assertGreater(second, first)

    def test_remaining_time_uses_confirmation_timeout(self) -> None:
        cm = ConversationManager(activity_timeout=60.0, confirmation_timeout=10.0)
        cm.request_confirmation("close_app", {"app_name": "notepad"}, "close notepad")
        self.assertEqual(cm.state, ConversationState.WAITING_CONFIRMATION)
        rt = cm.remaining_time
        self.assertLess(rt, 10.0 + 1e-6)
