"""
voice/manager.py

Voice provider coordinator.
"""

from __future__ import annotations

from typing import Any

from config.settings import settings
from voice.elevenlabs_provider import ElevenLabsProvider
from voice.provider import VoiceProvider
from voice.system_provider import SystemProvider


class VoiceManager:
    """Load the configured voice provider and expose speech output."""

    def __init__(self, config: Any = settings) -> None:
        self._settings = config
        self._diagnostics: list[str] = []
        try:
            self._provider = self._load_provider()
        except Exception as exc:
            self._diagnostics.append(
                f"Voice provider initialization failed; using system voice. ({exc})"
            )
            self._provider = self._system_provider()

    def speak(self, text: str) -> bool:
        """Speak text through the configured provider."""
        try:
            spoken = self._provider.speak(text)
        except Exception:
            spoken = False

        if spoken:
            return True

        if isinstance(self._provider, SystemProvider):
            return False

        self._diagnostics.append(
            "Configured voice provider failed while speaking; using system voice."
        )
        self._provider = self._system_provider()
        try:
            return self._provider.speak(text)
        except Exception:
            return False

    @property
    def diagnostics(self) -> tuple[str, ...]:
        """Friendly voice configuration diagnostics from initialization/runtime."""
        return tuple(self._diagnostics)

    def _load_provider(self) -> VoiceProvider:
        provider = self._provider_name()
        if provider == "system":
            return self._system_provider()

        if provider == "elevenlabs":
            api_key = self._elevenlabs_api_key()
            voice_id = self._voice_id()
            if not api_key:
                self._diagnostics.append(
                    "ELEVENLABS_API_KEY is missing; using system voice."
                )
                return self._system_provider()
            if not voice_id:
                self._diagnostics.append("VOICE_ID is missing; using system voice.")
                return self._system_provider()
            try:
                return ElevenLabsProvider(
                    api_key=api_key,
                    voice_id=voice_id,
                    model=self._voice_model(),
                )
            except Exception as exc:
                self._diagnostics.append(
                    f"ElevenLabs provider failed to initialize; using system voice. ({exc})"
                )
                return self._system_provider()

        self._diagnostics.append(
            f"Unsupported VOICE_PROVIDER {provider!r}; using system voice."
        )
        return self._system_provider()

    def _provider_name(self) -> str:
        return str(getattr(self._settings, "voice_provider", "system")).strip().casefold()

    def _system_provider(self) -> SystemProvider:
        return SystemProvider(voice_id=self._voice_id())

    def _voice_id(self) -> str:
        return str(getattr(self._settings, "voice_id", "") or "").strip()

    def _voice_model(self) -> str:
        return str(
            getattr(self._settings, "voice_model", "eleven_multilingual_v2")
            or "eleven_multilingual_v2"
        ).strip()

    def _elevenlabs_api_key(self) -> str:
        return str(getattr(self._settings, "elevenlabs_api_key", "") or "").strip()
