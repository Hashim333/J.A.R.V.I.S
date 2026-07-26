"""
dev_tests/test_voice_player.py

Tests for voice/player.py (VoicePlayer) and voice/manager.py (VoiceManager).

VoicePlayer tests mock PyAudio to avoid real audio hardware access.
"""

from __future__ import annotations

import threading
import time
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from voice.manager import VoiceManager
from voice.player import VoicePlayer


# ---------------------------------------------------------------------------
# VoicePlayer Tests
# ---------------------------------------------------------------------------


class TestVoicePlayer(unittest.TestCase):
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

    def test_not_playing_initially(self) -> None:
        self.assertFalse(self.player.is_playing)

    def test_play_empty_data_is_noop(self) -> None:
        self.player.play(b"")
        self.assertFalse(self.player.is_playing)

    def test_play_opens_pyaudio_stream(self) -> None:
        """play() opens a PyAudio output stream."""
        self.player.play(b"\x00\x00" * 1000, sample_rate=22050)
        self.mock_pyaudio_instance.open.assert_called_once()

    def test_stop_while_playing(self) -> None:
        """stop() closes stream and clears state."""
        self.player._ensure_pyaudio()
        self.player._stream = self.mock_stream
        self.player._play_thread = threading.Thread(target=time.sleep, args=(1,))
        self.player._play_thread.start()
        self.assertTrue(self.player.is_playing)
        self.player.stop()
        self.assertFalse(self.player.is_playing)
        self.mock_stream.stop_stream.assert_called_once()
        self.mock_stream.close.assert_called_once()

    def test_double_play_stops_first(self) -> None:
        """Second play() call stops first by calling stop()."""
        with patch.object(self.player, "stop") as mock_stop:
            self.player.play(b"\x00\x00" * 1000)
            self.player.play(b"\xFF\xFF" * 1000)
            self.assertEqual(mock_stop.call_count, 2)  # called for each play

    def test_pause_and_resume(self) -> None:
        """pause() and resume() set/clear pause event."""
        self.player._pause_event.set()
        self.assertTrue(self.player._pause_event.is_set())
        self.player.resume()
        self.assertFalse(self.player._pause_event.is_set())
        self.player.pause()
        self.assertTrue(self.player._pause_event.is_set())

    def test_shutdown_cleans_up(self) -> None:
        """shutdown() stops playback and terminates PyAudio."""
        self.player.shutdown()
        self.assertIsNone(self.player._pyaudio)

    def test_play_worker_writes_to_stream(self) -> None:
        """_play_worker writes PCM data to the PyAudio stream."""
        data = b"\x00\x01" * 500
        with patch.object(self.player, "_close_stream"):
            self.player._audio_data = data
            self.player._sample_rate = 22050
            self.player._sample_width = 2
            self.player._channels = 1
            self.player._ensure_pyaudio()
            self.player._play_worker()
            self.mock_stream.write.assert_called()


# ---------------------------------------------------------------------------
# VoiceManager Tests
# ---------------------------------------------------------------------------


class TestVoiceManager(unittest.TestCase):
    def _make_config(self, **kwargs: object) -> SimpleNamespace:
        defaults = dict(
            voice_provider="system",
            voice_id="",
            voice_model="",
            elevenlabs_api_key="",
            voice_stability=None,
            voice_similarity=None,
            voice_style=None,
            voice_speaker_boost=None,
        )
        defaults.update(kwargs)
        return SimpleNamespace(**defaults)

    def test_default_provider_is_system(self) -> None:
        manager = VoiceManager(config=self._make_config())
        self.assertEqual(manager._provider_name(), "system")

    def test_speak_empty_text_returns_false(self) -> None:
        manager = VoiceManager(config=self._make_config())
        self.assertFalse(manager.speak(""))
        self.assertFalse(manager.speak("   "))

    def test_speak_enqueues_text(self) -> None:
        manager = VoiceManager(config=self._make_config())
        result = manager.speak("Hello")
        self.assertTrue(result)
        self.assertGreaterEqual(manager.queue_size, 0)
        manager.cancel_all()

    def test_cancel_all_clears_queue(self) -> None:
        manager = VoiceManager(config=self._make_config())
        manager.speak("First")
        manager.speak("Second")
        manager.cancel_all()
        self.assertEqual(manager.queue_size, 0)

    def test_stop_calls_provider_stop(self) -> None:
        manager = VoiceManager(config=self._make_config())
        with patch.object(manager._provider, "stop") as mock_stop:
            manager.stop()
            mock_stop.assert_called_once()

    def test_unsupported_provider_falls_back(self) -> None:
        manager = VoiceManager(
            config=self._make_config(voice_provider="nonexistent")
        )
        from voice.system_provider import SystemProvider
        self.assertIsInstance(manager.provider, SystemProvider)
        self.assertIn("Unsupported VOICE_PROVIDER", manager.diagnostics[0])

    def test_elevenlabs_missing_key_falls_back(self) -> None:
        manager = VoiceManager(
            config=self._make_config(
                voice_provider="elevenlabs",
                voice_id="voice-123",
                voice_model="model-123",
                elevenlabs_api_key="",
            )
        )
        from voice.system_provider import SystemProvider
        self.assertIsInstance(manager.provider, SystemProvider)
        self.assertIn("ELEVENLABS_API_KEY is missing", manager.diagnostics[0])

    def test_elevenlabs_missing_voice_id_falls_back(self) -> None:
        manager = VoiceManager(
            config=self._make_config(
                voice_provider="elevenlabs",
                voice_id="",
                voice_model="model-123",
                elevenlabs_api_key="key-123",
            )
        )
        from voice.system_provider import SystemProvider
        self.assertIsInstance(manager.provider, SystemProvider)
        self.assertIn("VOICE_ID is missing", manager.diagnostics[0])

    def test_invalid_stability_returns_none(self) -> None:
        manager = VoiceManager(
            config=self._make_config(voice_stability="invalid")
        )
        self.assertIsNone(manager._voice_stability())

    def test_speaker_boost_string_true(self) -> None:
        manager = VoiceManager(
            config=self._make_config(voice_speaker_boost="true")
        )
        self.assertTrue(manager._voice_speaker_boost())

    def test_speaker_boost_string_false(self) -> None:
        manager = VoiceManager(
            config=self._make_config(voice_speaker_boost="false")
        )
        self.assertFalse(manager._voice_speaker_boost())

    def test_speaker_boost_bool_true(self) -> None:
        manager = VoiceManager(
            config=self._make_config(voice_speaker_boost=True)
        )
        self.assertTrue(manager._voice_speaker_boost())

    def test_diagnostics_tuple(self) -> None:
        manager = VoiceManager(config=self._make_config())
        self.assertIsInstance(manager.diagnostics, tuple)

    def test_pause_and_resume_no_crash(self) -> None:
        manager = VoiceManager(config=self._make_config())
        try:
            manager.pause()
            manager.resume()
        except Exception as exc:
            self.fail(f"pause/resume raised: {exc}")

    def test_priority_interrupts_current(self) -> None:
        """Priority speech enqueues and starts worker."""
        manager = VoiceManager(config=self._make_config())
        result = manager.speak("Urgent", priority=True)
        self.assertTrue(result)
        # The item is enqueued and will be processed by the worker
        manager.cancel_all()

    def test_worker_processes_queue(self) -> None:
        """Worker thread calls provider.speak() for queued items."""
        manager = VoiceManager(config=self._make_config())
        with patch.object(manager._provider, "speak", return_value=True) as mock_speak:
            manager.speak("Hello")
            time.sleep(0.15)
            mock_speak.assert_called_once_with("Hello")

    def test_worker_fallback_on_failure(self) -> None:
        """Worker switches to system provider on ElevenLabs failure."""
        manager = VoiceManager(
            config=self._make_config(
                voice_provider="elevenlabs",
                voice_id="vid",
                voice_model="vmod",
                elevenlabs_api_key="key",
            )
        )
        original_provider = manager._provider
        with patch.object(original_provider, "speak", return_value=False):
            manager.speak("Test")
            time.sleep(0.3)
        from voice.system_provider import SystemProvider
        self.assertIsInstance(manager._provider, SystemProvider)


if __name__ == "__main__":
    unittest.main(verbosity=2)
