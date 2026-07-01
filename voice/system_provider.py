"""
voice/system_provider.py

Windows System TTS provider implementation.
"""

from __future__ import annotations

import sys
import threading
import time
from typing import Iterable

from voice.provider import SpeechProvider

try:
    import win32com.client
except ImportError:  # pragma: no cover
    win32com = None


class SystemProvider(SpeechProvider):
    """Windows system text-to-speech provider."""

    def __init__(self, voice_id: str | None = None) -> None:
        self._voice_id = voice_id
        self._engine = None
        self._lock = threading.Lock()
        self._paused = False
        self._queue: list[str] = []
        self._thread: threading.Thread | None = None
        self._stop_requested = False

        if sys.platform != "win32":
            raise RuntimeError("Windows System TTS is only supported on Windows.")
        if win32com is None:
            raise RuntimeError("win32com is required for Windows System TTS.")

        self._engine = win32com.client.Dispatch("SAPI.SpVoice")
        if self._voice_id:
            self.set_voice(self._voice_id)

    def speak(self, text: str) -> bool:
        with self._lock:
            self._queue.append(text)
            if self._thread is None or not self._thread.is_alive():
                self._stop_requested = False
                self._thread = threading.Thread(target=self._run_queue, daemon=True)
                self._thread.start()
        return True

    def _run_queue(self) -> None:
        while True:
            with self._lock:
                if self._stop_requested:
                    self._queue.clear()
                    break
                if self._paused or not self._queue:
                    pass
                else:
                    utterance = self._queue.pop(0)
                    self._engine.Speak(utterance)
            time.sleep(0.1)
            with self._lock:
                if not self._queue and not self._paused and self._stop_requested:
                    break

    def stop(self) -> bool:
        with self._lock:
            self._stop_requested = True
            self._queue.clear()
        return True

    def pause(self) -> bool:
        with self._lock:
            self._paused = True
        return True

    def resume(self) -> bool:
        with self._lock:
            self._paused = False
        return True

    def set_voice(self, voice_id: str) -> bool:
        if not voice_id or not isinstance(voice_id, str):
            return False
        self._voice_id = voice_id
        if self._engine is not None:
            for voice in self._engine.GetVoices():
                if voice_id.lower() in str(voice.Id).lower() or voice_id.lower() in str(voice.GetDescription()).lower():
                    self._engine.Voice = voice
                    return True
        return False

    def available_voices(self) -> Iterable[str]:
        if self._engine is None:
            return []
        return [str(voice.Id) for voice in self._engine.GetVoices()]
