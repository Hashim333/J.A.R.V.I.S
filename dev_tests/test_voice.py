from __future__ import annotations

import importlib
import unittest
from abc import ABC
from types import SimpleNamespace
from unittest.mock import patch

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
        with patch.dict("os.environ", {"VOICE_PROVIDER": "system"}):
            import config.settings as settings_module

            reloaded = importlib.reload(settings_module)

        self.assertEqual(reloaded.settings.voice_provider, "system")

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


if __name__ == "__main__":
    unittest.main()
