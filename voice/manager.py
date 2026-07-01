"""
voice/manager.py

Central voice manager for JARVIS.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Iterable
from typing import Any

from config.settings import settings
from voice.elevenlabs_provider import ElevenLabsProvider
from voice.provider import SpeechProvider
from voice.system_provider import SystemProvider


class VoiceManager:
    """Manage active speech provider and queue spoken output."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._queue: list[str] = []
        self._provider_name = settings.voice_provider.strip().casefold()
        self._current_provider = self._create_provider()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._stop_requested = False
        self._paused = False
        self._thread.start()

    def _create_provider(self) -> SpeechProvider:
        provider_name = self._provider_name or "system"
        if provider_name == "elevenlabs":
            if settings.elevenlabs_api_key:
                try:
                    return ElevenLabsProvider(
                        api_key=settings.elevenlabs_api_key,
                        voice_id=settings.voice_id,
                        model=settings.voice_model,
                    )
                except Exception:
                    return SystemProvider(voice_id=settings.voice_id)
            return SystemProvider(voice_id=settings.voice_id)

        return SystemProvider(voice_id=settings.voice_id)

    def speak(self, text: str) -> bool:
        if not isinstance(text, str) or not text.strip():
            return False
        with self._lock:
            self._stop_requested = False
            self._queue.append(text.strip())
        return True

    def stop(self) -> bool:
        with self._lock:
            self._queue.clear()
            self._stop_requested = True
            self._current_provider.stop()
        return True

    def pause(self) -> bool:
        with self._lock:
            self._paused = True
            self._current_provider.pause()
        return True

    def resume(self) -> bool:
        with self._lock:
            self._paused = False
            self._current_provider.resume()
        return True

    def set_voice(self, voice_id: str) -> bool:
        with self._lock:
            return self._current_provider.set_voice(voice_id)

    def change_provider(self, provider_name: str) -> bool:
        normalized = provider_name.strip().casefold()
        with self._lock:
            self._provider_name = normalized
            self._current_provider = self._create_provider()
        return True

    def available_voices(self) -> Iterable[str]:
        return self._current_provider.available_voices()

    def _run(self) -> None:
        while True:
            if self._stop_requested:
                time.sleep(0.1)
                continue
            if self._paused:
                time.sleep(0.1)
                continue
            next_text = None
            with self._lock:
                if self._queue and not self._paused:
                    next_text = self._queue.pop(0)
            if next_text is not None:
                try:
                    self._current_provider.speak(next_text)
                except Exception:
                    # Fall back to system TTS when the active provider fails.
                    if not isinstance(self._current_provider, SystemProvider):
                        self._current_provider = SystemProvider(voice_id=settings.voice_id)
                        self._current_provider.speak(next_text)
            time.sleep(0.1)
