"""
tests/test_voice_states.py

Unit tests for voice/voice_states.py — the explicit six-state voice
lifecycle (Idle, Listening, Thinking, Speaking, Interrupted, Cancelled)
with finally-safe return-to-Idle guarantees.
"""

from __future__ import annotations

import unittest
from unittest.mock import Mock

from voice.voice_states import (
    VoiceState,
    VoiceStateManager,
    set_global_state_handler,
)


class TestVoiceStatesBasics(unittest.TestCase):
    def test_initial_state_is_idle(self) -> None:
        states = VoiceStateManager()
        self.assertEqual(states.state, VoiceState.IDLE)
        self.assertEqual(states.name, "Idle")

    def test_initial_state_can_be_overridden(self) -> None:
        states = VoiceStateManager(initial=VoiceState.LISTENING)
        self.assertEqual(states.state, VoiceState.LISTENING)

    def test_named_transitions(self) -> None:
        states = VoiceStateManager()
        states.on_listening("wake")
        self.assertEqual(states.state, VoiceState.LISTENING)
        states.on_thinking()
        self.assertEqual(states.state, VoiceState.THINKING)
        states.on_speaking()
        self.assertEqual(states.state, VoiceState.SPEAKING)
        states.on_interrupted()
        self.assertEqual(states.state, VoiceState.INTERRUPTED)
        states.on_cancelled()
        self.assertEqual(states.state, VoiceState.CANCELLED)
        states.return_to_idle()
        self.assertEqual(states.state, VoiceState.IDLE)

    def test_same_state_transition_is_noop(self) -> None:
        states = VoiceStateManager()
        states._on_change = Mock()
        states.set_state(VoiceState.IDLE, "no-op")
        states._on_change.assert_not_called()

    def test_set_state_rejects_non_enum(self) -> None:
        states = VoiceStateManager()
        with self.assertRaises(TypeError):
            states.set_state("LISTENING")  # type: ignore[arg-type]

    def test_full_cycle_round_trip(self) -> None:
        """Idle -> Listening -> Thinking -> Speaking -> Interrupted -> Idle."""
        states = VoiceStateManager()
        for enter in (
            states.on_listening,
            states.on_thinking,
            states.on_speaking,
            states.on_interrupted,
        ):
            enter()
        self.assertEqual(states.state, VoiceState.INTERRUPTED)
        states.return_to_idle()
        self.assertEqual(states.state, VoiceState.IDLE)


class TestVoiceStatesObservers(unittest.TestCase):
    def tearDown(self) -> None:
        set_global_state_handler(None)

    def test_on_change_receives_old_and_new(self) -> None:
        events: list[tuple[VoiceState, VoiceState]] = []
        states = VoiceStateManager(on_change=lambda old, new: events.append((old, new)))
        states.on_listening("wake word")
        self.assertEqual(events, [(VoiceState.IDLE, VoiceState.LISTENING)])

    def test_global_handler_receives_transitions(self) -> None:
        events: list[tuple[VoiceState, VoiceState]] = []
        set_global_state_handler(lambda old, new: events.append((old, new)))
        states = VoiceStateManager()
        states.on_speaking()
        self.assertEqual(events, [(VoiceState.IDLE, VoiceState.SPEAKING)])

    def test_failing_observers_do_not_break_state(self) -> None:
        states = VoiceStateManager(on_change=lambda old, new: (_ for _ in ()).throw(RuntimeError("boom")))
        set_global_state_handler(lambda old, new: (_ for _ in ()).throw(RuntimeError("boom")))
        # Must not raise; the state still advances.
        states.on_listening("noisy observers")
        self.assertEqual(states.state, VoiceState.LISTENING)


class TestVoiceStatesFinallySafe(unittest.TestCase):
    def test_transition_returns_to_idle_on_success(self) -> None:
        states = VoiceStateManager()
        with states.transition(VoiceState.LISTENING, "capture"):
            self.assertEqual(states.state, VoiceState.LISTENING)
        self.assertEqual(states.state, VoiceState.IDLE)

    def test_transition_returns_to_idle_on_exception(self) -> None:
        states = VoiceStateManager()
        with self.assertRaises(RuntimeError):
            with states.transition(VoiceState.SPEAKING, "tts"):
                self.assertEqual(states.state, VoiceState.SPEAKING)
                raise RuntimeError("tts crashed")
        self.assertEqual(states.state, VoiceState.IDLE)

    def test_nested_transitions_land_on_idle(self) -> None:
        states = VoiceStateManager()
        with states.transition(VoiceState.LISTENING):
            with states.transition(VoiceState.SPEAKING):
                self.assertEqual(states.state, VoiceState.SPEAKING)
            # The inner transition's finally always lands on Idle, never
            # re-entering the outer state.
            self.assertEqual(states.state, VoiceState.IDLE)
        self.assertEqual(states.state, VoiceState.IDLE)


if __name__ == "__main__":
    unittest.main()
