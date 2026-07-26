"""
dev_tests/test_config.py

Tests for config/settings.py — .env loading, validation, and summary.
"""

from __future__ import annotations

import importlib
import io
import sys
import unittest
from unittest.mock import patch

from config.settings import (
    _mask_key,
    _bool_env,
    _float_env,
    _str_env,
    get_diagnostics,
    print_config_summary,
    validate_config,
    Settings,
)


class TestConfigLoading(unittest.TestCase):
    """Tests that settings load correctly from environment variables."""

    def test_missing_env_uses_defaults(self) -> None:
        with patch("dotenv.load_dotenv"):
            with patch.dict("os.environ", {}, clear=True):
                import config.settings as settings_module

                reloaded = importlib.reload(settings_module)

        s = reloaded.settings
        self.assertEqual(s.voice_provider, "system")
        self.assertEqual(s.ollama_base_url, "http://localhost:11434")
        self.assertEqual(s.model, "qwen2.5:3b")
        self.assertEqual(s.timeout, 30)
        self.assertFalse(s.debug)
        self.assertFalse(s.voice_enabled)

    def test_empty_env_produces_defaults(self) -> None:
        """Empty .env (no values set) produces all defaults."""
        with patch("dotenv.load_dotenv"):
            with patch.dict("os.environ", {}, clear=True):
                import config.settings as settings_module

                reloaded = importlib.reload(settings_module)

        s = reloaded.settings
        self.assertEqual(s.voice_provider, "system")
        self.assertFalse(s.voice_enabled)
        self.assertEqual(s.voice_id, "")
        self.assertEqual(s.voice_model, "eleven_multilingual_v2")
        self.assertEqual(s.elevenlabs_api_key, "")
        self.assertEqual(s.voice_stability, 0.5)
        self.assertEqual(s.voice_similarity, 0.75)
        self.assertEqual(s.voice_style, 0.0)
        self.assertTrue(s.voice_speaker_boost)
        self.assertFalse(s.push_to_talk_enabled)
        self.assertEqual(s.push_to_talk_key, "F9")
        self.assertEqual(s.ollama_base_url, "http://localhost:11434")
        self.assertEqual(s.model, "qwen2.5:3b")
        self.assertEqual(s.timeout, 30)
        self.assertFalse(s.debug)

    def test_voice_config_loading(self) -> None:
        """Voice-specific env vars load correctly."""
        with patch("dotenv.load_dotenv"):
            with patch.dict(
                "os.environ",
                {
                    "VOICE_ENABLED": "true",
                    "VOICE_PROVIDER": "elevenlabs",
                    "VOICE_ID": "test-voice-id",
                    "VOICE_MODEL": "eleven_monolingual_v1",
                    "VOICE_STABILITY": "0.8",
                    "VOICE_SIMILARITY": "0.9",
                    "VOICE_STYLE": "0.2",
                    "VOICE_SPEAKER_BOOST": "false",
                    "PUSH_TO_TALK_ENABLED": "true",
                    "PUSH_TO_TALK_KEY": "Ctrl+Space",
                },
            ):
                import config.settings as settings_module

                reloaded = importlib.reload(settings_module)

        s = reloaded.settings
        self.assertTrue(s.voice_enabled)
        self.assertEqual(s.voice_provider, "elevenlabs")
        self.assertEqual(s.voice_id, "test-voice-id")
        self.assertEqual(s.voice_model, "eleven_monolingual_v1")
        self.assertEqual(s.voice_stability, 0.8)
        self.assertEqual(s.voice_similarity, 0.9)
        self.assertEqual(s.voice_style, 0.2)
        self.assertFalse(s.voice_speaker_boost)
        self.assertTrue(s.push_to_talk_enabled)
        self.assertEqual(s.push_to_talk_key, "Ctrl+Space")

    def test_ollama_config_loading(self) -> None:
        """Ollama-specific env vars load correctly."""
        with patch("dotenv.load_dotenv"):
            with patch.dict(
                "os.environ",
                {
                    "OLLAMA_BASE_URL": "http://192.168.1.100:11434",
                    "OLLAMA_MODEL": "llama3:8b",
                    "OLLAMA_TIMEOUT": "120",
                },
            ):
                import config.settings as settings_module

                reloaded = importlib.reload(settings_module)

        s = reloaded.settings
        self.assertEqual(s.ollama_base_url, "http://192.168.1.100:11434")
        self.assertEqual(s.model, "llama3:8b")
        self.assertEqual(s.timeout, 120)

    def test_debug_on_accepted(self) -> None:
        """'on' is accepted as a truthy boolean for DEBUG."""
        with patch("dotenv.load_dotenv"):
            with patch.dict("os.environ", {"DEBUG": "on"}):
                import config.settings as settings_module

                reloaded = importlib.reload(settings_module)

        self.assertTrue(reloaded.settings.debug)

    def test_env_override(self) -> None:
        with patch("dotenv.load_dotenv"):
            with patch.dict(
                "os.environ",
                {
                    "VOICE_PROVIDER": "elevenlabs",
                    "VOICE_ID": "voice-abc",
                    "ELEVENLABS_API_KEY": "sk-123",
                    "OLLAMA_BASE_URL": "http://10.0.0.1:11434",
                    "OLLAMA_TIMEOUT": "60",
                    "DEBUG": "true",
                },
            ):
                import config.settings as settings_module

                reloaded = importlib.reload(settings_module)

        s = reloaded.settings
        self.assertEqual(s.voice_provider, "elevenlabs")
        self.assertEqual(s.voice_id, "voice-abc")
        self.assertEqual(s.elevenlabs_api_key, "sk-123")
        self.assertEqual(s.ollama_base_url, "http://10.0.0.1:11434")
        self.assertEqual(s.timeout, 60)
        self.assertTrue(s.debug)


class TestConfigValidation(unittest.TestCase):
    """Tests for the validate_config() function."""

    def _settings(self, **overrides: object) -> Settings:
        defaults: dict[str, object] = dict(
            ollama_base_url="http://localhost:11434",
            model="qwen2.5:3b",
            timeout=30,
            debug=False,
            voice_enabled=False,
            voice_provider="system",
            voice_id="",
            voice_model="eleven_multilingual_v2",
            elevenlabs_api_key="",
            voice_stability=0.5,
            voice_similarity=0.75,
            voice_style=0.0,
            voice_speaker_boost=True,
            push_to_talk_enabled=False,
            push_to_talk_key="F9",
            mic_sensitivity=1.0,
            mic_agc_enabled=True,
            mic_agc_target_level=0.15,
            mic_noise_gate_enabled=True,
            mic_noise_gate_threshold=0.02,
        )
        defaults.update(overrides)
        return Settings(**defaults)  # type: ignore[arg-type]

    def test_valid_system_provider_passes(self) -> None:
        msgs = validate_config(self._settings())
        self.assertEqual(msgs, [])

    def test_successful_startup_all_valid(self) -> None:
        """Simulates a fully valid production configuration."""
        msgs = validate_config(
            self._settings(
                voice_provider="elevenlabs",
                voice_id="abc123def",
                elevenlabs_api_key="sk_a1b2c3d4e5f6",
                voice_model="eleven_multilingual_v2",
                voice_stability=0.5,
                voice_similarity=0.8,
                voice_style=0.1,
                voice_speaker_boost=True,
                ollama_base_url="http://localhost:11434",
                timeout=30,
            )
        )
        self.assertEqual(msgs, [])

    def test_valid_elevenlabs_passes(self) -> None:
        msgs = validate_config(
            self._settings(
                voice_provider="elevenlabs",
                voice_id="voice-abc",
                elevenlabs_api_key="sk-123",
            )
        )
        self.assertEqual(msgs, [])

    def test_invalid_provider(self) -> None:
        msgs = validate_config(self._settings(voice_provider="azure"))
        self.assertTrue(
            any("Invalid VOICE_PROVIDER" in m for m in msgs)
        )

    def test_elevenlabs_missing_api_key(self) -> None:
        msgs = validate_config(
            self._settings(
                voice_provider="elevenlabs",
                voice_id="voice-abc",
                elevenlabs_api_key="",
            )
        )
        self.assertTrue(
            any("API key is missing" in m for m in msgs)
        )

    def test_elevenlabs_missing_voice_id(self) -> None:
        msgs = validate_config(
            self._settings(
                voice_provider="elevenlabs",
                voice_id="",
                elevenlabs_api_key="sk-123",
            )
        )
        self.assertTrue(
            any("VOICE_ID is missing" in m for m in msgs)
        )

    def test_invalid_ollama_url(self) -> None:
        msgs = validate_config(
            self._settings(ollama_base_url="localhost:11434")
        )
        self.assertTrue(
            any("OLLAMA_BASE_URL" in m for m in msgs)
        )

    def test_timeout_zero(self) -> None:
        msgs = validate_config(self._settings(timeout=0))
        self.assertTrue(
            any("OLLAMA_TIMEOUT" in m for m in msgs)
        )

    def test_float_out_of_range_high(self) -> None:
        msgs = validate_config(self._settings(voice_stability=1.5))
        self.assertTrue(
            any("VOICE_STABILITY" in m for m in msgs)
        )

    def test_float_out_of_range_low(self) -> None:
        msgs = validate_config(self._settings(voice_similarity=-0.1))
        self.assertTrue(
            any("VOICE_SIMILARITY" in m for m in msgs)
        )

    def test_elevenlabs_empty_model(self) -> None:
        msgs = validate_config(
            self._settings(
                voice_provider="elevenlabs",
                voice_id="voice-abc",
                elevenlabs_api_key="sk-123",
                voice_model="",
            )
        )
        self.assertTrue(
            any("VOICE_MODEL" in m for m in msgs)
        )

    def test_multiple_errors_collected(self) -> None:
        msgs = validate_config(
            self._settings(
                voice_provider="elevenlabs",
                voice_id="",
                elevenlabs_api_key="",
                ollama_base_url="bad-url",
                timeout=-5,
            )
        )
        self.assertGreaterEqual(len(msgs), 3)


class TestConfigHelpers(unittest.TestCase):
    """Tests for internal helper functions."""

    def test_str_env_trim(self) -> None:
        with patch.dict("os.environ", {"TEST_KEY": "  value  "}):
            self.assertEqual(_str_env("TEST_KEY", ""), "value")

    def test_str_env_default(self) -> None:
        self.assertEqual(_str_env("NONEXISTENT", "fallback"), "fallback")

    def test_bool_env_true(self) -> None:
        for val in ("1", "true", "True", "yes"):
            with patch.dict("os.environ", {"TEST_KEY": val}):
                self.assertTrue(_bool_env("TEST_KEY", False))

    def test_bool_env_false(self) -> None:
        for val in ("0", "false", "False", "no", ""):
            with patch.dict("os.environ", {"TEST_KEY": val}):
                self.assertFalse(_bool_env("TEST_KEY", True))

    def test_bool_env_default(self) -> None:
        self.assertTrue(_bool_env("NONEXISTENT", True))
        self.assertFalse(_bool_env("NONEXISTENT", False))

    def test_float_env_parses(self) -> None:
        with patch.dict("os.environ", {"TEST_KEY": "0.75"}):
            self.assertEqual(_float_env("TEST_KEY", 0.5), 0.75)

    def test_float_env_invalid_uses_default(self) -> None:
        with patch.dict("os.environ", {"TEST_KEY": "abc"}):
            self.assertEqual(_float_env("TEST_KEY", 0.5), 0.5)

    def test_float_env_default(self) -> None:
        self.assertEqual(_float_env("NONEXISTENT", 0.5), 0.5)


class TestMaskKey(unittest.TestCase):
    """Tests for API key masking."""

    def test_masks_long_key(self) -> None:
        self.assertEqual(_mask_key("abc12345"), "ab****45")

    def test_masks_short_key(self) -> None:
        self.assertEqual(_mask_key("ab"), "********")

    def test_masks_empty_key(self) -> None:
        self.assertEqual(_mask_key(""), "********")


class TestConfigSummary(unittest.TestCase):
    """Tests for the config summary printer."""

    def setUp(self) -> None:
        self._buf = io.StringIO()
        self._stdout = sys.stdout
        sys.stdout = self._buf

    def tearDown(self) -> None:
        sys.stdout = self._stdout

    def test_summary_contains_expected_sections(self) -> None:
        s = Settings(
            ollama_base_url="http://localhost:11434",
            model="qwen2.5:3b",
            timeout=30,
            debug=False,
            voice_enabled=True,
            voice_provider="elevenlabs",
            voice_id="voice-123",
            voice_model="eleven_multilingual_v2",
            elevenlabs_api_key="sk-1234567890",
            voice_stability=0.5,
            voice_similarity=0.75,
            voice_style=0.0,
            voice_speaker_boost=True,
            push_to_talk_enabled=False,
            push_to_talk_key="F9",
            mic_sensitivity=1.0,
            mic_agc_enabled=True,
            mic_agc_target_level=0.15,
            mic_noise_gate_enabled=True,
            mic_noise_gate_threshold=0.02,
        )
        print_config_summary(s)
        output = self._buf.getvalue()
        self.assertIn("Configuration Loaded", output)
        self.assertIn("Elevenlabs", output)
        self.assertIn("voice-123", output)
        self.assertIn("sk****90", output)
        self.assertIn("http://localhost:11434", output)
        self.assertIn("Mic Sensitivity", output)
        self.assertIn("Mic AGC", output)
        self.assertIn("Mic Noise Gate", output)

    def test_summary_api_key_not_set(self) -> None:
        s = Settings(
            ollama_base_url="http://localhost:11434",
            model="qwen2.5:3b",
            timeout=30,
            debug=False,
            voice_enabled=False,
            voice_provider="system",
            voice_id="",
            voice_model="eleven_multilingual_v2",
            elevenlabs_api_key="",
            voice_stability=0.5,
            voice_similarity=0.75,
            voice_style=0.0,
            voice_speaker_boost=True,
            push_to_talk_enabled=False,
            push_to_talk_key="F9",
            mic_sensitivity=1.0,
            mic_agc_enabled=True,
            mic_agc_target_level=0.15,
            mic_noise_gate_enabled=True,
            mic_noise_gate_threshold=0.02,
        )
        print_config_summary(s)
        output = self._buf.getvalue()
        self.assertIn("(not set)", output)
        self.assertNotIn("****", output)


class TestFlatAliases(unittest.TestCase):
    """Tests for the module-level flat aliases."""

    def test_flat_aliases_match_settings(self) -> None:
        """Module-level constants match Settings fields."""
        import config.settings as m

        self.assertEqual(m.OLLAMA_BASE_URL, m.settings.ollama_base_url)
        self.assertEqual(m.OLLAMA_MODEL, m.settings.model)
        self.assertEqual(m.OLLAMA_TIMEOUT, m.settings.timeout)
        self.assertEqual(m.DEBUG, m.settings.debug)
        self.assertEqual(m.VOICE_ENABLED, m.settings.voice_enabled)
        self.assertEqual(m.VOICE_PROVIDER, m.settings.voice_provider)
        self.assertEqual(m.VOICE_ID, m.settings.voice_id)
        self.assertEqual(m.VOICE_MODEL, m.settings.voice_model)
        self.assertEqual(m.ELEVENLABS_API_KEY, m.settings.elevenlabs_api_key)
        self.assertEqual(m.VOICE_STABILITY, m.settings.voice_stability)
        self.assertEqual(m.VOICE_SIMILARITY, m.settings.voice_similarity)
        self.assertEqual(m.VOICE_STYLE, m.settings.voice_style)
        self.assertEqual(m.VOICE_SPEAKER_BOOST, m.settings.voice_speaker_boost)
        self.assertEqual(m.PUSH_TO_TALK_ENABLED, m.settings.push_to_talk_enabled)
        self.assertEqual(m.PUSH_TO_TALK_KEY, m.settings.push_to_talk_key)


class TestGetDiagnostics(unittest.TestCase):
    """Tests for the diagnostics accessor."""

    def test_diagnostics_are_accessible(self) -> None:
        result = get_diagnostics()
        self.assertIsInstance(result, tuple)


if __name__ == "__main__":
    unittest.main(verbosity=2)
