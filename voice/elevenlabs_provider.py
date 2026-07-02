"""
voice/elevenlabs_provider.py

ElevenLabs text-to-speech provider.
"""

from __future__ import annotations

import json
import os
import tempfile
import urllib.error
import urllib.request
from socket import timeout as SocketTimeout

from config.settings import settings
from voice.provider import VoiceProvider


ELEVENLABS_URL = "https://api.elevenlabs.io/v1/text-to-speech"


class ElevenLabsProvider(VoiceProvider):
    """Speak through ElevenLabs using configuration-provided credentials."""

    def __init__(
        self,
        api_key: str | None = None,
        voice_id: str | None = None,
        model: str | None = None,
        *,
        timeout: int = 30,
    ) -> None:
        self._api_key = api_key if api_key is not None else settings.elevenlabs_api_key
        self._voice_id = voice_id if voice_id is not None else settings.voice_id
        self._model = model if model is not None else settings.voice_model
        self._timeout = timeout

    def speak(self, text: str) -> bool:
        if not isinstance(text, str) or not text.strip():
            return False
        if not self._api_key:
            return False
        if not self._voice_id:
            return False

        request = self._build_request(text.strip())
        try:
            with urllib.request.urlopen(request, timeout=self._timeout) as response:
                audio = response.read()
        except (
            urllib.error.HTTPError,
            urllib.error.URLError,
            SocketTimeout,
            TimeoutError,
            OSError,
        ):
            return False

        if not audio:
            return False

        return self._play_audio(audio)

    def _build_request(self, text: str) -> urllib.request.Request:
        body = json.dumps(
            {
                "text": text,
                "model_id": self._model,
            }
        ).encode("utf-8")

        return urllib.request.Request(
            f"{ELEVENLABS_URL}/{self._voice_id}",
            data=body,
            headers={
                "Accept": "audio/mpeg",
                "Content-Type": "application/json",
                "xi-api-key": self._api_key or "",
            },
            method="POST",
        )

    @staticmethod
    def _play_audio(audio: bytes) -> bool:
        with tempfile.NamedTemporaryFile(delete=False, suffix=".mp3") as tmp:
            tmp.write(audio)
            audio_path = tmp.name

        try:
            os.startfile(audio_path)  # type: ignore[attr-defined]
        except (AttributeError, OSError):
            return False
        return True
