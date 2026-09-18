"""
tests/test_piper_provider.py

Unit tests for the Piper (local offline TTS) fallback provider and the
VoiceManager fallback chain:

  * PiperProvider mirrors the ElevenLabsProvider shape (speak/stop/
    is_playing/pause/resume/player) and never crashes on a missing model
    or missing piper package — it just returns False.
  * Piper model path resolution (relative paths anchored at the project
    root, as read from PIPER_VOICE_MODEL_PATH).
  * VoiceManager runtime fallback order:
      ElevenLabs (primary) -> Piper (local) -> system voice (last resort).

No piper install or model download is required: piper is never imported
at module load, and the model file is fabricated with ``patch``.
"""

from __future__ import annotations

import tempfile
import threading
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from voice.manager import VoiceManager
from voice.piper_provider import PiperProvider
from voice.provider import VoiceProvider


class _FakePlayer:
    """Record play() calls instead of touching PyAudio."""

    def __init__(self) -> None:
        self.calls: list[dict] = []
        self.is_playing = False

    def play(self, audio_data, sample_rate=22050, sample_width=2, channels=1) -> None:
        self.calls.append({
            "audio": audio_data,
            "sample_rate": sample_rate,
            "sample_width": sample_width,
            "channels": channels,
        })

    def stop(self) -> None:
        self.is_playing = False

    def pause(self) -> None:
        pass

    def resume(self) -> None:
        pass


class _FakeVoice:
    """Mimics the newer piper.synthesize(text) -> (audio, sample_rate)."""

    def synthesize(self, text: str):
        import numpy as np

        audio = np.zeros(2205, dtype=np.int16)  # 0.1 s of silence at 22050 Hz
        return audio, 22050


class _FakeVoiceStream:
    """Mimics the older piper.synthesize_stream_raw shape."""

    config: SimpleNamespace
    config = SimpleNamespace(sample_rate=22050)

    def synthesize(self, text: str):
        raise TypeError("old API")

    def synthesize_stream_raw(self, text: str):
        import numpy as np

        yield np.zeros(2205, dtype=np.int16)
        yield np.zeros(1103, dtype=np.int16)


def _empty_model_dir() -> Path:
    """A temp dir with a *.onnx placeholder file (PiperProvider only checks
    the file's existence)."""
    tmp = tempfile.mkdtemp(prefix="piper-proc-test-")
    path = Path(tmp) / "en_US-fake-medium.onnx"
    path.write_bytes(b"noc")
    return path


def _config(provider: str = "elevenlabs", **overrides) -> SimpleNamespace:
    base = dict(
        voice_provider=provider,
        voice_id="voice-123",
        voice_model="model-123",
        elevenlabs_api_key="key-123",
        piper_voice_model_path="",
        piper_voice_name="en_US-fake-medium",
    )
    base.update(overrides)
    return SimpleNamespace(**base)


class TestPiperProviderProtocol(unittest.TestCase):
    def test_implements_voice_provider_interface(self) -> None:
        self.assertTrue(issubclass(PiperProvider, VoiceProvider))

    def test_missing_model_speak_returns_false(self) -> None:
        provider = PiperProvider(
            model_path=str(_empty_model_dir().parent / "does-not-exist.onnx"),
            voice_name="en_US-fake-medium",
            player=_FakePlayer(),  # type: ignore[arg-type]
        )
        self.assertFalse(provider.model_available)
        self.assertFalse(provider.speak("hello world"))

    def test_missing_model_never_raises(self) -> None:
        provider = PiperProvider(
            model_path=str(_empty_model_dir().parent / "nope.onnx"),
            player=_FakePlayer(),  # type: ignore[arg-type]
        )
        # stop/pause/resume must not crash even with no model
        provider.stop()
        provider.pause()
        provider.resume()
        self.assertFalse(provider.is_playing)

    def test_empty_text_is_refused(self) -> None:
        provider = PiperProvider(
            model_path=str(_empty_model_dir()),
            player=_FakePlayer(),  # type: ignore[arg-type]
        )
        self.assertFalse(provider.speak("   "))

    def test_model_path_resolves_relative_to_project_root(self) -> None:
        from config.settings import ROOT_DIR

        with patch("voice.piper_provider.settings") as mock:
            mock.piper_voice_model_path = "models/piper/x.onnx"
            provider = PiperProvider(player=_FakePlayer())  # type: ignore[arg-type]
        self.assertEqual(provider.model_path, ROOT_DIR / "models" / "piper" / "x.onnx")

    def test_dont_warn_when_real_model_exists(self) -> None:
        model = _empty_model_dir()
        provider = PiperProvider(
            model_path=str(model),
            player=_FakePlayer(),  # type: ignore[arg-type]
        )
        self.assertTrue(provider.model_available)


class TestPiperSynthesis(unittest.TestCase):
    """speak() drives the same VoicePlayer.play(...) the ElevenLabs provider
    uses, feeding Piper's 22050 Hz 16-bit mono PCM."""

    def test_play_backend_synthesize_and_player_shape(self) -> None:
        model = _empty_model_dir()
        player = _FakePlayer()
        with patch(
            "voice.piper_provider.PiperProvider._ensure_voice",
            return_value=_FakeVoice(),
        ):
            provider = PiperProvider(model_path=str(model), player=player)  # type: ignore[arg-type]
            ok = self._speak_without_thread_issue(provider, "open chrome")

        self.assertTrue(ok)
        self.assertEqual(len(player.calls), 1)
        call = player.calls[0]
        self.assertEqual(call["sample_rate"], 22050)
        self.assertEqual(call["sample_width"], 2)
        self.assertEqual(call["channels"], 1)
        self.assertTrue(call["audio"])

    def test_synthesis_failure_returns_false(self) -> None:
        model = _empty_model_dir()
        with patch(
            "voice.piper_provider.PiperProvider._ensure_voice", return_value=_FakeVoice()
        ):
            provider = PiperProvider(model_path=str(model), player=_FakePlayer())  # type: ignore[arg-type]
            with patch.object(_FakeVoice, "synthesize", side_effect=RuntimeError("boom")):
                self.assertFalse(provider.speak("hello"))

    def test_playback_failure_returns_false(self) -> None:
        model = _empty_model_dir()
        player = _FakePlayer()

        def boom(audio, **kwargs):
            raise RuntimeError("port audio down")

        with patch(
            "voice.piper_provider.PiperProvider._ensure_voice", return_value=_FakeVoice()
        ):
            provider = PiperProvider(model_path=str(model), player=player)  # type: ignore[arg-type]
            player.play = boom  # type: ignore[method-assign]
            self.assertFalse(provider.speak("hello"))

    def _speak_without_thread_issue(self, provider, text: str) -> bool:
        """Speak synchronously and let the worker thread finish."""
        # _FakePlayer.play is synchronous; just call speak() directly.
        return provider.speak(text)


class TestPiperFallbackChain(unittest.TestCase):
    """VoiceManager: ElevenLabs (primary) -> Piper -> system voice."""

    def test_elevenlabs_failure_switches_to_piper(self) -> None:
        model = _empty_model_dir()
        manager = VoiceManager(
            config=_config(piper_voice_model_path=str(model)),
        )
        from voice.elevenlabs_provider import ElevenLabsProvider

        self.assertIsInstance(manager._provider, ElevenLabsProvider)

        with (
            patch.object(manager._provider, "speak", return_value=False),
            patch("voice.piper_provider.PiperProvider._ensure_voice",
                  return_value=_FakeVoice()),
        ):
            manager.speak("Hello")
            self._wait_for(manager)

        from voice.piper_provider import PiperProvider

        self.assertIsInstance(manager._provider, PiperProvider)
        self.assertIn(
            "Switching to Piper (local) voice provider",
            manager.diagnostics[-1],
        )
        manager.shutdown()

    def test_missing_piper_model_falls_directly_to_system(self) -> None:
        from voice.system_provider import SystemProvider

        manager = VoiceManager(
            config=_config(piper_voice_model_path="models/piper/missing.onnx"),
        )
        # ElevenLabs fails -> _fallback_to_piper() sees no model -> system.
        with patch.object(manager._provider, "speak", return_value=False):
            manager.speak("Hi")
            self._wait_for(manager)

        self.assertIsInstance(manager._provider, SystemProvider)
        self.assertIn(
            "Switching to system voice provider",
            manager.diagnostics[-1],
        )
        manager.shutdown()

    def test_piper_available_stays_as_fallback(self) -> None:
        model = _empty_model_dir()
        manager = VoiceManager(
            config=_config(piper_voice_model_path=str(model)),
        )
        with (
            patch.object(manager._provider, "speak", return_value=False),
            patch("voice.piper_provider.PiperProvider._ensure_voice",
                  return_value=_FakeVoice()),
        ):
            manager.speak("Hello")
            self._wait_for(manager)

        from voice.piper_provider import PiperProvider

        self.assertIsInstance(manager._provider, PiperProvider)
        manager.shutdown()

    def test_config_missing_piper_does_not_break_elevenlabs_load(self) -> None:
        model = _empty_model_dir()
        manager = VoiceManager(config=_config(piper_voice_model_path=str(model)))
        manager.shutdown()
        from voice.elevenlabs_provider import ElevenLabsProvider

        self.assertIsInstance(manager._provider, ElevenLabsProvider)

    @staticmethod
    def _wait_for(manager: VoiceManager, timeout: float = 3.0) -> None:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if manager.provider is not None and not manager.is_busy:
                return
            time.sleep(0.02)


if __name__ == "__main__":
    unittest.main()