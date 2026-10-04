"""
dev_tests/test_bridge_state_transitions.py

Tests for the Bridge state machine with fake sequences.
Tests include interrupt during SPEAKING state.
"""

from __future__ import annotations

import threading
import time
import unittest
from unittest.mock import MagicMock, patch

from ui.bridge import Bridge, UIState


class TestBridgeStateTransitions(unittest.TestCase):
    """Test the Bridge state machine with various sequences."""

    def setUp(self):
        self.bridge = Bridge()
        self.transitions: list[dict] = []
        self._capture_thread: threading.Thread | None = None
        self._stop_capture = threading.Event()

        # Capture all stateChanged emissions
        def on_state_changed(payload):
            self.transitions.append(payload.copy())

        self.bridge.stateChanged.connect(on_state_changed)

    def tearDown(self):
        self._stop_capture.set()
        if self._capture_thread is not None:
            self._capture_thread.join(timeout=1.0)

    def _wait_for_transition(self, target_state: str, timeout: float = 2.0) -> bool:
        """Wait for a specific state transition."""
        start = time.monotonic()
        while time.monotonic() - start < timeout:
            if any(t.get("state") == target_state for t in self.transitions):
                return True
            time.sleep(0.01)
        return False

    def _get_unique_states(self) -> list[str]:
        """Get unique consecutive states (deduplicate)."""
        if not self.transitions:
            return []
        unique = [self.transitions[0]["state"]]
        for t in self.transitions[1:]:
            if t["state"] != unique[-1]:
                unique.append(t["state"])
        return unique

    def test_passive_to_listening_to_thinking_to_working_to_speaking_to_done(self):
        """Test the full happy path: PASSIVE -> LISTENING -> THINKING -> WORKING -> SPEAKING -> DONE -> PASSIVE"""
        self.bridge.emit_passive("Ready")
        self.bridge.emit_listening("Listening...")
        self.bridge.emit_thinking("Thinking...")
        self.bridge.emit_working("Working...")
        self.bridge.emit_speaking("Speaking...")
        self.bridge.emit_done("Done")
        self.bridge.emit_passive("Ready again")

        unique_states = self._get_unique_states()
        self.assertEqual(unique_states, [
            UIState.PASSIVE.value,
            UIState.LISTENING.value,
            UIState.THINKING.value,
            UIState.WORKING.value,
            UIState.SPEAKING.value,
            UIState.DONE.value,
            UIState.PASSIVE.value,
        ])

    def test_interrupt_during_speaking(self):
        """Test interrupt during SPEAKING state -> ERROR -> PASSIVE"""
        self.bridge.emit_passive("Ready")
        self.bridge.emit_listening("Listening...")
        self.bridge.emit_thinking("Thinking...")
        self.bridge.emit_speaking("Speaking long text...")

        self.assertTrue(self._wait_for_transition(UIState.SPEAKING.value))

        self.bridge.emit_error("Speech interrupted", "Interrupted")

        self.assertTrue(self._wait_for_transition(UIState.ERROR.value))

        unique_states = self._get_unique_states()
        self.assertIn(UIState.SPEAKING.value, unique_states)
        self.assertIn(UIState.ERROR.value, unique_states)

    def test_wake_word_sequence(self):
        """Test WAKE -> LISTENING sequence"""
        self.bridge.emit_passive("Ready")
        self.bridge.emit_wake("Wake word detected")
        self.bridge.emit_listening("Listening...")

        unique_states = self._get_unique_states()
        self.assertEqual(unique_states, [
            UIState.PASSIVE.value,
            UIState.WAKE.value,
            UIState.LISTENING.value,
        ])

    def test_error_recovery(self):
        """Test ERROR -> PASSIVE recovery"""
        self.bridge.emit_passive("Ready")
        self.bridge.emit_listening("Listening...")
        self.bridge.emit_error("Something went wrong", "Error")
        self.bridge.emit_passive("Recovered")

        unique_states = self._get_unique_states()
        self.assertEqual(unique_states, [
            UIState.PASSIVE.value,
            UIState.LISTENING.value,
            UIState.ERROR.value,
            UIState.PASSIVE.value,
        ])

    def test_audio_level_propagation(self):
        """Test that audio levels are properly propagated in LISTENING state."""
        self.bridge.emit_listening("Listening...", audio_level=0.5)
        self.bridge.emit_listening("Recording...", audio_level=0.8)

        listening_transitions = [t for t in self.transitions if t["state"] == UIState.LISTENING.value]
        audio_levels = [t["audio_level"] for t in listening_transitions if t["audio_level"] is not None]
        self.assertIn(0.5, audio_levels)
        self.assertIn(0.8, audio_levels)

    def test_state_transition_log(self):
        """Test that transition log is maintained correctly."""
        self.bridge.emit_passive("Start")
        self.bridge.emit_listening("Listening")
        self.bridge.emit_thinking("Thinking")

        log = self.bridge.get_transition_log()
        self.assertGreaterEqual(len(log), 3)
        unique_from = [log[0]["from"]]
        unique_to = [log[0]["to"]]
        for entry in log[1:]:
            if entry["from"] != unique_from[-1]:
                unique_from.append(entry["from"])
            if entry["to"] != unique_to[-1]:
                unique_to.append(entry["to"])
        self.assertIn(UIState.PASSIVE.value, unique_from)
        self.assertIn(UIState.LISTENING.value, unique_from)
        self.assertIn(UIState.THINKING.value, unique_to)

    def test_concurrent_state_changes_thread_safe(self):
        """Test that state changes from multiple threads don't crash."""
        errors: list[Exception] = []

        def emit_states(thread_id: int):
            try:
                for i in range(3):
                    state = [
                        UIState.PASSIVE,
                        UIState.LISTENING,
                        UIState.THINKING,
                        UIState.WORKING,
                        UIState.SPEAKING,
                    ][i % 5]
                    self.bridge.emit_state(state, caption=f"Thread {thread_id} state {i}")
                    time.sleep(0.01)
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=emit_states, args=(i,)) for i in range(2)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=2.0)

        self.assertEqual(len(errors), 0, f"Thread errors: {errors}")

    def test_duplicate_state_suppressed(self):
        """Test that duplicate state transitions are suppressed."""
        self.bridge.emit_passive("Ready")
        self.bridge.emit_passive("Ready")

        passive_transitions = [t for t in self.transitions if t["state"] == UIState.PASSIVE.value]
        self.assertEqual(len(passive_transitions), 1)

    def test_legacy_compat_core_state(self):
        """Test that legacy set_core_state still works."""
        self.bridge.set_core_state("idle")
        self.bridge.set_core_state("listening")
        self.bridge.set_core_state("thinking")
        self.bridge.set_core_state("speaking")
        self.bridge.set_core_state("error")

        all_states = [t["state"] for t in self.transitions]
        self.assertIn(UIState.LISTENING.value, all_states)
        self.assertIn(UIState.THINKING.value, all_states)
        self.assertIn(UIState.SPEAKING.value, all_states)
        self.assertIn(UIState.ERROR.value, all_states)


class TestBridgeWithFakeComponents(unittest.TestCase):
    """Test Bridge integration with fake DuplexVoiceSession, VoiceManager, etc."""

    def test_duplex_session_emits_states(self):
        """Test that DuplexVoiceSession emits LISTENING/UNDERSTANDING states."""
        from voice.duplex import DuplexVoiceSession

        bridge = Bridge()
        transitions = []
        bridge.stateChanged.connect(lambda p: transitions.append(p.copy()))

        session = DuplexVoiceSession(bridge=bridge)
        self.assertIs(session._bridge, bridge)

        session._emit_state("LISTENING", "Test listening")
        session._emit_state("UNDERSTANDING", "Test understanding")

        listening = [t for t in transitions if t["state"] == "LISTENING"]
        understanding = [t for t in transitions if t["state"] == "UNDERSTANDING"]
        self.assertEqual(len(listening), 2)
        self.assertEqual(len(understanding), 2)

    def test_voice_manager_emits_speaking_done(self):
        """Test that VoiceManager emits SPEAKING and DONE states."""
        from voice.manager import VoiceManager

        bridge = Bridge()
        transitions = []
        bridge.stateChanged.connect(lambda p: transitions.append(p.copy()))

        manager = VoiceManager.__new__(VoiceManager)
        manager._settings = MagicMock()
        manager._diagnostics = []
        manager._queue = __import__('queue').Queue()
        manager._queue_lock = threading.Lock()
        manager._worker_thread = None
        manager._worker_start_lock = threading.Lock()
        manager._stop_worker = threading.Event()
        manager._current_text = None
        manager._interrupted = False
        manager._generation = 0
        manager._generation_lock = threading.Lock()
        manager._activity_lock = threading.Lock()
        manager._pending_utterances = 0
        manager._speech_finished_event = threading.Event()
        manager._speech_finished_event.set()
        manager.on_speech_finished = None
        manager._bridge = bridge
        manager._provider = MagicMock()
        manager._provider.speak = MagicMock(return_value=True)
        manager._provider.stop = MagicMock()
        manager._provider.is_playing = False

        if manager._bridge:
            manager._bridge.emit_speaking("Speaking...")
        if manager._bridge:
            manager._bridge.emit_done("Done speaking")

        speaking = [t for t in transitions if t["state"] == "SPEAKING"]
        done = [t for t in transitions if t["state"] == "DONE"]
        self.assertEqual(len(speaking), 2)
        self.assertEqual(len(done), 2)

    def test_wake_word_service_emits_wake(self):
        """Test that WakeWordService emits WAKE state."""
        from services.wake_word_service import WakeWordService

        bridge = Bridge()
        transitions = []
        bridge.stateChanged.connect(lambda p: transitions.append(p.copy()))

        event = threading.Event()
        service = WakeWordService(wake_word_detected_event=event, bridge=bridge)

        class FakeAudio:
            frame_data = b"test"
        service._on_wake_word(FakeAudio())

        wake = [t for t in transitions if t["state"] == "WAKE"]
        self.assertEqual(len(wake), 2)
        self.assertIn("Wake", wake[0]["caption"])


if __name__ == "__main__":
    unittest.main()