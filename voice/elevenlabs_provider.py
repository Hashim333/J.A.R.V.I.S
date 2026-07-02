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
from voice.provider import VoiceProvider, VoiceProviderError


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
            raise VoiceProviderError("ElevenLabs API key is not configured.")
        if not self._voice_id:
            raise VoiceProviderError("ElevenLabs voice ID is not configured.")

        request = self._build_request(text.strip())
        try:
            with urllib.request.urlopen(request, timeout=self._timeout) as response:
                audio = response.read()
        except urllib.error.HTTPError as exc:
            if exc.code in {401, 403}:
                raise VoiceProviderError(
                    "ElevenLabs authentication failed. Check ELEVENLABS_API_KEY."
                ) from exc
            raise VoiceProviderError(
                f"ElevenLabs request failed with HTTP {exc.code}."
            ) from exc
        except urllib.error.URLError as exc:
            raise VoiceProviderError(
                "Could not reach ElevenLabs. Check your network connection."
            ) from exc
        except SocketTimeout as exc:
            raise VoiceProviderError("ElevenLabs request timed out.") from exc
        except TimeoutError as exc:
            raise VoiceProviderError("ElevenLabs request timed out.") from exc

        if not audio:
            raise VoiceProviderError("ElevenLabs returned no audio.")

        self._play_audio(audio)
        return True

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
    def _play_audio(audio: bytes) -> None:
        with tempfile.NamedTemporaryFile(delete=False, suffix=".mp3") as tmp:
            tmp.write(audio)
            audio_path = tmp.name

        try:
            os.startfile(audio_path)  # type: ignore[attr-defined]
        except AttributeError as exc:
            raise VoiceProviderError(
                "ElevenLabs audio playback requires Windows os.startfile support."
            ) from exc
        except OSError as exc:
            raise VoiceProviderError("Could not play ElevenLabs audio.") from exc
