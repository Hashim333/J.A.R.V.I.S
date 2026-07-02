from __future__ import annotations

import importlib
import unittest
from abc import ABC
from types import SimpleNamespace
from unittest.mock import patch

from voice.elevenlabs_provider import ElevenLabsProvider
from voice.manager import VoiceManager
from voice.provider import SpeechProvider, VoiceProvider
from voice.system_provider import SystemProvider


class VoiceFoundationTests(unittest.TestCase):
    def test_voice_provider_is_abstract_interface(self) -> None:
        self.assertTrue(issubclass(VoiceProvider, ABC))
        self.assertIs(SpeechProvider, VoiceProvider)
        self.assertIn("speak", VoiceProvider.__abstractmethods__)

    def test_system_provider_speak_uses_windows_tts(self) -> None:
        provider = SystemProvider()
        completed = SimpleNamespace(returncode=0, stdout="", stderr="")

        with patch("voice.system_provider.subprocess.run", return_value=completed) as run:
            self.assertTrue(provider.speak("Hello"))

        args = run.call_args.args[0]
        self.assertIn("powershell", args[0])
        self.assertIn("System.Speech", args[-1])
        self.assertIn("Hello", args[-1])

    def test_system_provider_returns_false_for_blank_text(self) -> None:
        self.assertFalse(SystemProvider().speak("   "))

    def test_system_provider_returns_false_on_failure(self) -> None:
        provider = SystemProvider()
        completed = SimpleNamespace(returncode=1, stdout="", stderr="failed")

        with patch("voice.system_provider.subprocess.run", return_value=completed):
            self.assertFalse(provider.speak("Hello"))

    def test_configuration_defaults_to_system_provider(self) -> None:
        with patch.dict("os.environ", {}, clear=True):
            import config.settings as settings_module

            reloaded = importlib.reload(settings_module)

        self.assertEqual(reloaded.settings.voice_provider, "system")
        self.assertEqual(reloaded.VOICE_PROVIDER, "system")

    def test_configuration_loads_system_provider_env(self) -> None:
        with patch.dict("os.environ", {"VOICE_PROVIDER": " system "}):
            import config.settings as settings_module

            reloaded = importlib.reload(settings_module)

        self.assertEqual(reloaded.settings.voice_provider, "system")

    def test_configuration_loads_all_voice_environment_values(self) -> None:
        with patch.dict(
            "os.environ",
            {
                "VOICE_ENABLED": "true",
                "VOICE_PROVIDER": "elevenlabs",
                "VOICE_ID": "voice-123",
                "VOICE_MODEL": "model-123",
                "ELEVENLABS_API_KEY": "key-123",
            },
        ):
            import config.settings as settings_module

            reloaded = importlib.reload(settings_module)

        self.assertTrue(reloaded.settings.voice_enabled)
        self.assertEqual(reloaded.settings.voice_provider, "elevenlabs")
        self.assertEqual(reloaded.settings.voice_id, "voice-123")
        self.assertEqual(reloaded.settings.voice_model, "model-123")
        self.assertEqual(reloaded.settings.elevenlabs_api_key, "key-123")

    def test_voice_manager_initializes_system_provider(self) -> None:
        config = SimpleNamespace(voice_provider="system", voice_id="")

        manager = VoiceManager(config=config)

        self.assertIsInstance(manager._provider, SystemProvider)

    def test_voice_manager_speak_delegates_to_provider(self) -> None:
        config = SimpleNamespace(voice_provider="system", voice_id="")
        manager = VoiceManager(config=config)

        with patch.object(manager._provider, "speak", return_value=True) as speak:
            self.assertTrue(manager.speak("Hello"))

        speak.assert_called_once_with("Hello")

    def test_voice_manager_unsupported_provider_falls_back_to_system(self) -> None:
        config = SimpleNamespace(voice_provider="unknown", voice_id="")

        manager = VoiceManager(config=config)

        self.assertIsInstance(manager._provider, SystemProvider)
        self.assertIn("Unsupported VOICE_PROVIDER", manager.diagnostics[0])

    def test_voice_manager_selects_elevenlabs_provider(self) -> None:
        config = SimpleNamespace(
            voice_provider="elevenlabs",
            voice_id="voice-123",
            voice_model="model-123",
            elevenlabs_api_key="key-123",
        )

        manager = VoiceManager(config=config)

        self.assertIsInstance(manager._provider, ElevenLabsProvider)
        self.assertEqual(manager.diagnostics, ())

    def test_voice_manager_missing_api_key_falls_back_to_system(self) -> None:
        config = SimpleNamespace(
            voice_provider="elevenlabs",
            voice_id="voice-123",
            voice_model="model-123",
            elevenlabs_api_key="",
        )

        manager = VoiceManager(config=config)

        self.assertIsInstance(manager._provider, SystemProvider)
        self.assertIn("ELEVENLABS_API_KEY is missing", manager.diagnostics[0])

    def test_voice_manager_missing_voice_id_falls_back_to_system(self) -> None:
        config = SimpleNamespace(
            voice_provider="elevenlabs",
            voice_id="",
            voice_model="model-123",
            elevenlabs_api_key="key-123",
        )

        manager = VoiceManager(config=config)

        self.assertIsInstance(manager._provider, SystemProvider)
        self.assertIn("VOICE_ID is missing", manager.diagnostics[0])

    def test_voice_manager_elevenlabs_init_failure_falls_back_to_system(self) -> None:
        config = SimpleNamespace(
            voice_provider="elevenlabs",
            voice_id="voice-123",
            voice_model="model-123",
            elevenlabs_api_key="key-123",
        )

        with patch("voice.manager.ElevenLabsProvider", side_effect=RuntimeError("boom")):
            manager = VoiceManager(config=config)

        self.assertIsInstance(manager._provider, SystemProvider)
        self.assertIn("failed to initialize", manager.diagnostics[0])

    def test_voice_manager_runtime_provider_failure_falls_back_to_system(self) -> None:
        config = SimpleNamespace(
            voice_provider="elevenlabs",
            voice_id="voice-123",
            voice_model="model-123",
            elevenlabs_api_key="key-123",
        )
        manager = VoiceManager(config=config)

        with (
            patch.object(manager._provider, "speak", return_value=False),
            patch.object(SystemProvider, "speak", return_value=True),
        ):
            self.assertTrue(manager.speak("Hello"))

        self.assertIsInstance(manager._provider, SystemProvider)
        self.assertIn("failed while speaking", manager.diagnostics[-1])

    def test_voice_manager_missing_optional_settings_do_not_crash(self) -> None:
        manager = VoiceManager(config=SimpleNamespace(voice_provider="system"))

        self.assertIsInstance(manager._provider, SystemProvider)


if __name__ == "__main__":
    unittest.main()
