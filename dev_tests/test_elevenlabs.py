from __future__ import annotations

import importlib
import unittest
import urllib.error
from types import SimpleNamespace
from unittest.mock import patch

from voice.elevenlabs_provider import ElevenLabsProvider
from voice.manager import VoiceManager
from voice.system_provider import SystemProvider


class ElevenLabsProviderTests(unittest.TestCase):
    def test_configuration_loads_elevenlabs_settings(self) -> None:
        with patch.dict(
            "os.environ",
            {
                "VOICE_PROVIDER": "elevenlabs",
                "ELEVENLABS_API_KEY": "key-123",
                "VOICE_ID": "voice-123",
                "VOICE_MODEL": "model-123",
            },
        ):
            import config.settings as settings_module

            reloaded = importlib.reload(settings_module)

        self.assertEqual(reloaded.settings.voice_provider, "elevenlabs")
        self.assertEqual(reloaded.settings.elevenlabs_api_key, "key-123")
        self.assertEqual(reloaded.settings.voice_id, "voice-123")
        self.assertEqual(reloaded.settings.voice_model, "model-123")

    def test_voice_manager_selects_elevenlabs_provider(self) -> None:
        config = SimpleNamespace(
            voice_provider="elevenlabs",
            elevenlabs_api_key="key-123",
            voice_id="voice-123",
            voice_model="model-123",
        )

        manager = VoiceManager(config=config)

        self.assertIsInstance(manager._provider, ElevenLabsProvider)

    def test_voice_manager_falls_back_to_system_when_elevenlabs_init_fails(self) -> None:
        config = SimpleNamespace(
            voice_provider="elevenlabs",
            elevenlabs_api_key="key-123",
            voice_id="voice-123",
            voice_model="model-123",
        )

        with patch(
            "voice.manager.ElevenLabsProvider",
            side_effect=RuntimeError("init failed"),
        ):
            manager = VoiceManager(config=config)

        self.assertIsInstance(manager._provider, SystemProvider)

    def test_invalid_api_key_returns_false(self) -> None:
        provider = ElevenLabsProvider(
            api_key="bad-key",
            voice_id="voice-123",
            model="model-123",
        )
        error = urllib.error.HTTPError(
            url="https://api.elevenlabs.io",
            code=401,
            msg="Unauthorized",
            hdrs=None,
            fp=None,
        )

        with patch("voice.elevenlabs_provider.urllib.request.urlopen", side_effect=error):
            self.assertFalse(provider.speak("Hello"))

    def test_network_error_returns_false(self) -> None:
        provider = ElevenLabsProvider(
            api_key="key-123",
            voice_id="voice-123",
            model="model-123",
        )

        with patch(
            "voice.elevenlabs_provider.urllib.request.urlopen",
            side_effect=urllib.error.URLError("offline"),
        ):
            self.assertFalse(provider.speak("Hello"))

    def test_successful_request_returns_true(self) -> None:
        provider = ElevenLabsProvider(
            api_key="key-123",
            voice_id="voice-123",
            model="model-123",
        )

        class FakeResponse:
            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

            def read(self) -> bytes:
                return b"audio"

        with (
            patch("voice.elevenlabs_provider.urllib.request.urlopen", return_value=FakeResponse()),
            patch("voice.elevenlabs_provider.os.startfile", create=True),
        ):
            self.assertTrue(provider.speak("Hello"))


if __name__ == "__main__":
    unittest.main()
