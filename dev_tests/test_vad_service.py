"""
dev_tests/test_vad_service.py

Deterministic unit tests for voice.vad.VAD and
services.wake_word_service.WakeWordService.

These tests do NOT require:

- microphone hardware
- real speech
- real webrtcvad decisions

Everything is mocked so the tests behave identically on every machine.
"""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch
import threading

from services.wake_word_service import WakeWordService
from voice.vad import VAD


SAMPLE_RATE = 16000
FRAME_MS = 30
FRAME_SIZE = int(SAMPLE_RATE * FRAME_MS / 1000) * 2
FRAME = b"\x00" * FRAME_SIZE


class TestVAD(unittest.TestCase):
    """Tests the VAD class directly."""

    def setUp(self):
        self.started = MagicMock()
        self.ended = MagicMock()

    def create_vad(self):
        return VAD(
            on_speech_started=self.started,
            on_speech_ended=self.ended,
        )

    def feed(self, vad, count):
        for _ in range(count):
            vad.process_audio(FRAME)

    @patch("voice.vad.webrtcvad.Vad.is_speech", return_value=False)
    def test_silence_does_not_trigger_callbacks(self, _):
        vad = self.create_vad()

        self.feed(vad, 20)

        self.started.assert_not_called()
        self.ended.assert_not_called()

    @patch("voice.vad.webrtcvad.Vad.is_speech", return_value=True)
    def test_speech_triggers_started_callback(self, _):
        vad = self.create_vad()

        needed = vad._ring_buffer.maxlen

        self.feed(vad, needed)

        self.started.assert_called_once()
        self.ended.assert_not_called()

    def test_speech_then_silence(self):
        vad = self.create_vad()

        needed = vad._ring_buffer.maxlen

        with patch(
            "voice.vad.webrtcvad.Vad.is_speech",
            return_value=True,
        ):
            self.feed(vad, needed)

        self.started.assert_called_once()

        with patch(
            "voice.vad.webrtcvad.Vad.is_speech",
            return_value=False,
        ):
            self.feed(vad, needed)

        self.ended.assert_called_once()


class TestWakeWordService(unittest.TestCase):
    """Tests WakeWordService behaviour."""

    def setUp(self):
        self.wake_word_event = threading.Event()
        self.service = WakeWordService(wake_word_detected_event=self.wake_word_event)
        self.service.initialize()
        self.assertIsNotNone(self.service._vad)

    def test_initial_state(self):
        """Speech event should initially be cleared."""
        self.assertFalse(self.wake_word_event.is_set())

    def test_speech_sets_event(self):
        """Speech detection should set the event."""
        needed = self.service._vad._ring_buffer.maxlen

        with patch(
            "voice.vad.webrtcvad.Vad.is_speech",
            return_value=True,
        ):
            for _ in range(needed):
                self.service._vad.process_audio(FRAME)

        self.assertTrue(self.wake_word_event.is_set())

    def test_speech_then_silence_leaves_event_set(self):
        """Speech followed by silence should leave the event set."""
        needed = self.service._vad._ring_buffer.maxlen

        with patch(
            "voice.vad.webrtcvad.Vad.is_speech",
            return_value=True,
        ):
            for _ in range(needed):
                self.service._vad.process_audio(FRAME)

        self.assertTrue(self.wake_word_event.is_set())

        with patch(
            "voice.vad.webrtcvad.Vad.is_speech",
            return_value=False,
        ):
            for _ in range(needed):
                self.service._vad.process_audio(FRAME)

        # The service no longer clears the event; the consumer is responsible.
        self.assertTrue(self.wake_word_event.is_set())

    def test_invalid_frame_size_is_ignored(self):
        """Frames with invalid length should be ignored."""
        invalid = b"\x00" * 100

        with patch(
            "voice.vad.webrtcvad.Vad.is_speech"
        ) as mock_is_speech:
            self.service._vad.process_audio(invalid)

        mock_is_speech.assert_not_called()

    def test_multiple_speech_periods(self):
        """The service should correctly detect multiple speech periods."""
        needed = self.service._vad._ring_buffer.maxlen

        for i in range(2):
            self.wake_word_event.clear()
            self.assertFalse(self.wake_word_event.is_set())

            with patch(
                "voice.vad.webrtcvad.Vad.is_speech",
                return_value=True,
            ):
                for _ in range(needed):
                    self.service._vad.process_audio(FRAME)

            self.assertTrue(
                self.wake_word_event.is_set(),
                f"Event not set on iteration {i}",
            )

            with patch(
                "voice.vad.webrtcvad.Vad.is_speech",
                return_value=False,
            ):
                for _ in range(needed):
                    self.service._vad.process_audio(FRAME)

            self.assertTrue(
                self.wake_word_event.is_set(),
                f"Event was cleared on iteration {i}",
            )


if __name__ == "__main__":
    unittest.main()