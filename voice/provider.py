"""
voice/provider.py

Abstract interface for speech synthesis providers.
"""

from __future__ import annotations

from abc import ABC, abstractmethod


class VoiceProviderError(RuntimeError):
    """Raised when a voice provider cannot speak the requested text."""


class VoiceProvider(ABC):
    """Interface implemented by all voice providers.

    Providers convert text into audio. The audio is played through
    a shared VoicePlayer instance for low-latency, interruptible
    output.
    """

    @abstractmethod
    def speak(self, text: str) -> bool:
        """Synthesise and play *text*.

        Returns True when the provider accepted the request.
        The actual audio plays asynchronously on a background thread.
        Call stop() to interrupt.
        """
        raise NotImplementedError

    def stop(self) -> None:
        """Cancel any in-progress speech immediately. Default no-op."""
        return

    @property
    def is_playing(self) -> bool:
        """True when this provider is currently playing audio."""
        return False

    def pause(self) -> None:
        """Pause playback. Call resume() to continue. Default no-op."""
        return

    def resume(self) -> None:
        """Resume paused playback. Default no-op."""
        return


# Backward-compatible alias for older imports in the voice package.
SpeechProvider = VoiceProvider
