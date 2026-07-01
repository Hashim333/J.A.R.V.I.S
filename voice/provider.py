"""
voice/provider.py

Abstraction layer for all speech synthesis providers.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Iterable


class SpeechProvider(ABC):
    """Abstract interface for a text-to-speech provider."""

    @abstractmethod
    def speak(self, text: str) -> bool:
        raise NotImplementedError

    @abstractmethod
    def stop(self) -> bool:
        raise NotImplementedError

    @abstractmethod
    def pause(self) -> bool:
        raise NotImplementedError

    @abstractmethod
    def resume(self) -> bool:
        raise NotImplementedError

    @abstractmethod
    def set_voice(self, voice_id: str) -> bool:
        raise NotImplementedError

    @abstractmethod
    def available_voices(self) -> Iterable[str]:
        raise NotImplementedError
