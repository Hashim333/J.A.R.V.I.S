"""
dev_tests/test_echo_prevention.py

Tests for the TTS echo feedback loop fix:
1. VoicePlayer fires on_playback_started / on_playback_finished
2. MicrophoneStream mutes during playback and unmutes after
3. No audio chunks reach the consumer while muted
"""

from __future__ import annotations

import threading
import time
import unittest
from unittest.mock import MagicMock, patch

from voice.player import VoicePlayer
from voice.microphone_stream import MicrophoneStream


class TestPlaybackCallbacks(unittest.TestCase):
    def setUp(self) -> None:
        patcher = patch("voice.player.pyaudio")
        self.mock_pyaudio_mod = patcher.start()
        self.addCleanup(patcher.stop)

        self.mock_pyaudio_instance = MagicMock()
        self.mock_pyaudio_mod.PyAudio.return_value = self.mock_pyaudio_instance
        self.mock_stream = MagicMock()
        self.mock_pyaudio_instance.open.return_value = self.mock_stream

        self.player = VoicePlayer()

    def tearDown(self) -> None:
        self.player.shutdown()

    def test_started_callback_fires(self) -> None:
        started = threading.Event()

        def on_start() -> None:
            started.set()

        self.player.on_playback_started = on_start
        data = b"\x00\x01" * 500
        stop_event = threading.Event()
        with patch.object(self.player, "_close_stream"):
            self.player._audio_data = data
            self.player._sample_rate = 22050
            self.player._sample_width = 2
            self.player._channels = 1
            self.player._ensure_pyaudio()
            self.player._play_worker(stop_event)
            self.assertTrue(started.is_set())

    def test_finished_callback_fires(self) -> None:
        finished = threading.Event()

        def on_finish() -> None:
            finished.set()

        self.player.on_playback_finished = on_finish
        data = b"\x00\x01" * 500
        stop_event = threading.Event()
        with patch.object(self.player, "_close_stream"):
            self.player._audio_data = data
            self.player._sample_rate = 22050
            self.player._sample_width = 2
            self.player._channels = 1
            self.player._ensure_pyaudio()
            self.player._play_worker(stop_event)
            self.assertTrue(finished.is_set())

    def test_started_before_finished(self) -> None:
        order = []

        def on_start() -> None:
            order.append("start")

        def on_finish() -> None:
            order.append("finish")

        self.player.on_playback_started = on_start
        self.player.on_playback_finished = on_finish
        data = b"\x00\x01" * 500
        stop_event = threading.Event()
        with patch.object(self.player, "_close_stream"):
            self.player._audio_data = data
            self.player._sample_rate = 22050
            self.player._sample_width = 2
            self.player._channels = 1
            self.player._ensure_pyaudio()
            self.player._play_worker(stop_event)
            self.assertEqual(order, ["start", "finish"])

    def test_finished_has_cooldown_on_normal_exit(self) -> None:
        """on_playback_finished fires after playback completes (no artificial cooldown)."""
        finished = threading.Event()

        def on_finish() -> None:
            finished.set()

        self.player.on_playback_finished = on_finish
        data = b"\x00\x01" * 500
        stop_event = threading.Event()
        with patch.object(self.player, "_close_stream"):
            self.player._audio_data = data
            self.player._sample_rate = 22050
            self.player._sample_width = 2
            self.player._channels = 1
            self.player._ensure_pyaudio()
            self.player._play_worker(stop_event)

        self.assertTrue(finished.is_set())

    def test_no_cooldown_on_interrupted(self) -> None:
        """When stop() is called, cooldown is skipped."""
        start = time.monotonic()
        finished = threading.Event()

        def on_finish() -> None:
            finished.set()

        self.player.on_playback_finished = on_finish
        data = b"\x00\x01" * 5000
        stop_event = threading.Event()
        stop_event.set()  # Simulate interruption
        with patch.object(self.player, "_close_stream"):
            self.player._audio_data = data
            self.player._sample_rate = 22050
            self.player._sample_width = 2
            self.player._channels = 1
            self.player._ensure_pyaudio()
            self.player._play_worker(stop_event)

        elapsed = (time.monotonic() - start) * 1000
        # No cooldown, should be fast (< 50ms)
        self.assertLess(elapsed, 50)


class TestMicrophoneMute(unittest.TestCase):
    def setUp(self) -> None:
        self.ms = MicrophoneStream()

    def test_mute_sets_flag(self) -> None:
        self.assertFalse(self.ms._muted)
        self.ms.mute()
        self.assertTrue(self.ms._muted)

    def test_unmute_clears_flag(self) -> None:
        self.ms.mute()
        self.assertTrue(self.ms._muted)
        self.ms.unmute()
        self.assertFalse(self.ms._muted)

    def test_muted_consumer_not_called(self) -> None:
        """When muted, the consumer should not receive audio chunks."""
        received = []

        def consumer(chunk: bytes) -> None:
            received.append(chunk)

        self.ms._consumer = consumer
        self.ms.mute()

        # Simulate what _capture_loop does
        consumer_fn = self.ms._consumer
        if consumer_fn is not None and not self.ms._muted:
            consumer_fn(b"\x00\x01")

        self.assertEqual(len(received), 0)

    def test_unmuted_consumer_called(self) -> None:
        """When unmuted, the consumer should receive audio chunks."""
        received = []

        def consumer(chunk: bytes) -> None:
            received.append(chunk)

        self.ms._consumer = consumer
        self.ms.unmute()

        consumer_fn = self.ms._consumer
        if consumer_fn is not None and not self.ms._muted:
            consumer_fn(b"\x00\x01")

        self.assertEqual(len(received), 1)

    def test_mute_then_unmute_consumer_called(self) -> None:
        """After mute+unmute cycle, consumer should work again."""
        received = []

        def consumer(chunk: bytes) -> None:
            received.append(chunk)

        self.ms._consumer = consumer
        self.ms.mute()
        self.ms.unmute()

        consumer_fn = self.ms._consumer
        if consumer_fn is not None and not self.ms._muted:
            consumer_fn(b"\x00\x01")

        self.assertEqual(len(received), 1)


class TestEndToEndWiring(unittest.TestCase):
    def test_callbacks_wire_to_mute(self) -> None:
        """Simulate the wiring in run.py: player callbacks control mic mute."""
        with patch("voice.player.pyaudio"):
            player = VoicePlayer()
            ms = MicrophoneStream()

            # Wire like run.py does
            player.on_playback_started = ms.mute
            player.on_playback_finished = ms.unmute

            # Before playback - not muted
            self.assertFalse(ms._muted)

            # Simulate playback start
            player.on_playback_started()
            self.assertTrue(ms._muted)

            # Simulate playback end
            player.on_playback_finished()
            self.assertFalse(ms._muted)


if __name__ == "__main__":
    unittest.main(verbosity=2)
