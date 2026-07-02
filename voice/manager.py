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
        self._provider = self._load_provider()

    def speak(self, text: str) -> bool:
        """Speak text through the configured provider."""
        return self._provider.speak(text)

    def _load_provider(self) -> VoiceProvider:
        provider = self._provider_name()
        if provider == "system":
            return SystemProvider(voice_id=self._settings.voice_id)
        if provider == "elevenlabs":
            try:
                return ElevenLabsProvider(
                    api_key=self._settings.elevenlabs_api_key,
                    voice_id=self._settings.voice_id,
                    model=self._settings.voice_model,
                )
            except Exception:
                return SystemProvider(voice_id=self._settings.voice_id)
        return SystemProvider(voice_id=self._settings.voice_id)

    def _provider_name(self) -> str:
        return str(getattr(self._settings, "voice_provider", "system")).strip().casefold()
