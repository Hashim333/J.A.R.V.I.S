"""
dev_tests/test_vad_service.py

Deterministic unit tests for voice.vad.VAD and
services.wake_word_service.WakeWordService.

These tests do NOT require microphone hardware, real speech,
or real webrtcvad decisions.
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
        with patch("voice.vad.webrtcvad.Vad.is_speech", return_value=True):
            self.feed(vad, needed)
        self.started.assert_called_once()
        with patch("voice.vad.webrtcvad.Vad.is_speech", return_value=False):
            self.feed(vad, needed)
        self.ended.assert_called_once()


class TestWakeWordService(unittest.TestCase):
    """Tests WakeWordService behaviour via its WakeWordDetector."""

    def setUp(self):
        self.wake_word_event = threading.Event()
        self.service = WakeWordService(wake_word_detected_event=self.wake_word_event)
        self.service.initialize()
        # Access VAD through the detector
        self.detector = self.service._wake_word_detector
        self.assertIsNotNone(self.detector)
        self.vad = self.detector._vad

    def test_initial_state(self):
        """Speech event should initially be cleared."""
        self.assertFalse(self.wake_word_event.is_set())

    def _trigger_speech_start(self, detector):
        """Feed enough 'speech' frames to trigger VAD speech_started callback."""
        needed = detector._vad._ring_buffer.maxlen
        with patch("voice.vad.webrtcvad.Vad.is_speech", return_value=True):
            for _ in range(needed + 2):
                detector.process_audio(FRAME)

    def _trigger_speech_end(self, detector):
        """Feed 'silence' frames to trigger VAD speech_ended callback."""
        needed = detector._vad._ring_buffer.maxlen
        with patch("voice.vad.webrtcvad.Vad.is_speech", return_value=False):
            for _ in range(needed + 2):
                detector.process_audio(FRAME)

    @patch("voice.local_wake_word.LocalWakeWordDetector.contains_wake_word", return_value=True)
    def test_speech_sets_event(self, mock_contains):
        """Speech detection should set the event via wake-word detector."""
        self._trigger_speech_start(self.detector)
        self._trigger_speech_end(self.detector)
        self.assertTrue(self.wake_word_event.is_set())

    @patch("voice.local_wake_word.LocalWakeWordDetector.contains_wake_word", return_value=True)
    def test_speech_then_silence_leaves_event_set(self, mock_contains):
        """Speech followed by silence should leave the event set."""
        self._trigger_speech_start(self.detector)
        self._trigger_speech_end(self.detector)
        self.assertTrue(self.wake_word_event.is_set())
        # More silence should not clear the event
        self._trigger_speech_end(self.detector)
        self.assertTrue(self.wake_word_event.is_set())

    @patch("voice.vad.webrtcvad.Vad.is_speech")
    def test_invalid_frame_size_is_ignored(self, mock_is_speech):
        """Frames with invalid length should be buffered, not processed."""
        invalid = b"\x00" * 100
        self.detector.process_audio(invalid)
        # First call to is_speech will be when a full frame accumulates
        mock_is_speech.assert_not_called()
        # Feed a full frame next; the buffered fragment should combine
        self.detector.process_audio(FRAME)
        mock_is_speech.assert_called_once()

    @patch("voice.local_wake_word.LocalWakeWordDetector.contains_wake_word", return_value=True)
    def test_multiple_speech_periods(self, mock_contains):
        """The service should correctly handle multiple speech periods via reset."""
        for i in range(2):
            self.wake_word_event.clear()
            self.assertFalse(self.wake_word_event.is_set())
            self.service.reset_for_wake()
            self.detector = self.service._wake_word_detector
            self._trigger_speech_start(self.detector)
            self._trigger_speech_end(self.detector)
            self.assertTrue(
                self.wake_word_event.is_set(),
                f"Event not set on iteration {i}",
            )


if __name__ == "__main__":
    unittest.main()
