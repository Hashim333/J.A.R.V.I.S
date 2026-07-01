"""
voice/elevenlabs_provider.py

Provider wrapper for ElevenLabs text-to-speech.
"""

from __future__ import annotations

import json
import os
import tempfile
import urllib.request
import winsound
from typing import Iterable

from voice.provider import SpeechProvider

ELEVENLABS_URL = "https://api.elevenlabs.io/v1/text-to-speech"


class ElevenLabsProvider(SpeechProvider):
    """ElevenLabs TTS provider."""

    def __init__(self, api_key: str, voice_id: str | None = None, model: str = "eleven_multilingual_v2") -> None:
        self._api_key = api_key
        self._voice_id = voice_id
        self._model = model
        self._last_audio: bytes | None = None
        self._audio_file: str | None = None

    def speak(self, text: str) -> bool:
        if not self._api_key:
            raise RuntimeError("ElevenLabs API key is not configured.")
        if not self._voice_id:
            raise RuntimeError("ElevenLabs voice ID is not configured.")

        body = json.dumps({
            "text": text,
            "voice": self._voice_id,
            "model": self._model,
            "audio_format": "wav",
        }).encode("utf-8")

        request = urllib.request.Request(
            f"{ELEVENLABS_URL}/{self._voice_id}",
            data=body,
            headers={
                "Content-Type": "application/json",
                "xi-api-key": self._api_key,
                "Accept": "audio/wav",
            },
            method="POST",
        )

        with urllib.request.urlopen(request, timeout=30) as response:
            self._last_audio = response.read()

        if not self._last_audio:
            raise RuntimeError("ElevenLabs returned empty audio content.")

        with tempfile.NamedTemporaryFile(delete=False, suffix=".wav") as tmp:
            tmp.write(self._last_audio)
            tmp.flush()
            self._audio_file = tmp.name

        winsound.PlaySound(self._audio_file, winsound.SND_FILENAME | winsound.SND_SYNC)
        return True

    def stop(self) -> bool:
        self._last_audio = None
        if self._audio_file and os.path.exists(self._audio_file):
            try:
                os.remove(self._audio_file)
            except OSError:
                pass
        self._audio_file = None
        return True

    def pause(self) -> bool:
        return True

    def resume(self) -> bool:
        return True

    def set_voice(self, voice_id: str) -> bool:
        if not voice_id:
            return False
        self._voice_id = voice_id
        return True

    def available_voices(self) -> Iterable[str]:
        return []
