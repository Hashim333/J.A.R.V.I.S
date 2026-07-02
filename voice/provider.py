"""
voice/provider.py

Abstract interface for speech synthesis providers.
"""

from __future__ import annotations

from abc import ABC, abstractmethod


class VoiceProviderError(RuntimeError):
    """Raised when a voice provider cannot speak the requested text."""


class VoiceProvider(ABC):
    """Minimal interface implemented by all voice providers."""

    @abstractmethod
    def speak(self, text: str) -> bool:
        """Speak text and return True when the provider accepted it."""
        raise NotImplementedError


# Backward-compatible alias for older imports in the voice package.
SpeechProvider = VoiceProvider
