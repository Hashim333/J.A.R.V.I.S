"""
voice/piper_provider.py

Local, fully-offline Piper TTS provider (fallback after ElevenLabs).

Synthesises speech in-process via the ``piper-tts`` Python API (no
subprocess, no network) and plays the resulting PCM through a shared
VoicePlayer instance — the exact same playback pattern used by
``voice/elevenlabs_provider`` (``self._player.play(audio_data,
sample_rate=..., sample_width=2, channels=1)``).

The Piper voice model is NOT bundled with the repository and is NEVER
auto-downloaded by this module.  The user downloads it once, manually::

    python -m piper.download_voices en_US-lessac-medium

and places the generated ``en_US-lessac-medium.onnx`` (+ ``.onnx.json``)
at ``models/piper/`` (or wherever ``PIPER_VOICE_MODEL_PATH`` points).
When the model file is missing, ``speak()`` logs a clear warning and
returns ``False`` so the VoiceManager fallback chain continues to the
Windows system voice (last resort).  Piper failures NEVER crash the app.
"""

from __future__ import annotations

import logging
import threading
import time
from pathlib import Path
from typing import Any

from config.settings import ROOT_DIR, settings
from voice.player import VoicePlayer
from voice.provider import VoiceProvider

logger = logging.getLogger(__name__)

_DEFAULT_SAMPLE_RATE = 22050  # Piper's default output rate (16-bit mono PCM)


def _resolve_model_path(path: str | None) -> Path:
    """Resolve ``PIPER_VOICE_MODEL_PATH`` relative to the project root.

    Absolute paths pass through unchanged; relative paths (e.g. the
    ``models/piper/...`` style found in ``.env``) are anchored at
    ``config.settings.ROOT_DIR`` so they survive cwd changes.
    """
    raw = (path or settings.piper_voice_model_path or "").strip()
    candidate = Path(raw).expanduser()
    if candidate.is_absolute():
        return candidate
    return ROOT_DIR / candidate


class PiperProvider(VoiceProvider):
    """Speak through the local Piper TTS engine via VoicePlayer."""

    def __init__(
        self,
        model_path: str | None = None,
        voice_name: str | None = None,
        player: VoicePlayer | None = None,
    ) -> None:
        self._model_path = _resolve_model_path(model_path)
        self._voice_name = (
            voice_name if voice_name is not None else settings.piper_voice_name
        )
        self._player = player or VoicePlayer()
        self._stats: dict[str, Any] = {}
        self._voice = None  # lazy-loaded Piper voice (kept in-process)
        self._voice_loaded = False

        if not self._model_path.is_file():
            self._warn_model_missing()
        else:
            config_path = self._model_path.with_suffix(self._model_path.suffix)
            logger.info(
                "Piper: configured (model=%s, voice=%s, config=%s)",
                self._model_path, self._voice_name, config_path.name,
            )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def speak(self, text: str) -> bool:
        """Synthesise *text* with Piper and play through VoicePlayer.

        Returns True when synthesis + playback were accepted.  Any failure
        (missing model, missing piper package, synthesis error, playback
        error) returns False so the VoiceManager fallback chain continues.
        """
        if not isinstance(text, str) or not text.strip():
            return False
        if not self._model_path.is_file():
            self._warn_model_missing()
            return False

        payload = text.strip()
        start = time.monotonic()

        try:
            voice = self._ensure_voice()
            if voice is None:
                return False
            pcm, sample_rate = self._synthesize_pcm(voice, payload)
        except Exception as exc:  # noqa: BLE001
            logger.error(
                "Piper: synthesis failed (%d chars): %s", len(payload), exc,
                exc_info=True,
            )
            return False

        if not pcm:
            logger.error("Piper: synthesis produced empty audio (%d chars)", len(payload))
            return False

        elapsed = (time.monotonic() - start) * 1000
        self._stats["last_synthesis_ms"] = elapsed
        self._stats["last_sample_rate"] = sample_rate

        try:
            self._player.play(
                pcm,
                sample_rate=sample_rate,
                sample_width=2,
                channels=1,
            )
        except Exception as exc:  # noqa: BLE001
            logger.error("Piper: playback failed: %s", exc, exc_info=True)
            return False

        logger.info(
            "Piper: OK (%d chars, %.0f ms, %d Hz, %d bytes)",
            len(payload), elapsed, sample_rate, len(pcm),
        )
        return True

    def stop(self) -> None:
        """Stop playback immediately."""
        self._player.stop()
        logger.debug("Piper: stopped via player")

    @property
    def is_playing(self) -> bool:
        """True when audio is currently playing."""
        return self._player.is_playing

    def pause(self) -> None:
        """Pause playback."""
        self._player.pause()
        logger.debug("Piper: paused")

    def resume(self) -> None:
        """Resume paused playback."""
        self._player.resume()
        logger.debug("Piper: resumed")

    @property
    def player(self) -> VoicePlayer:
        """The shared VoicePlayer instance used for playback."""
        return self._player

    @property
    def stats(self) -> dict[str, Any]:
        """Return diagnostic statistics."""
        return dict(self._stats)

    @property
    def model_path(self) -> Path:
        """The resolved Piper voice model path."""
        return self._model_path

    @property
    def model_available(self) -> bool:
        """True when the Piper voice model file exists on disk."""
        return self._model_path.is_file()

    # ------------------------------------------------------------------
    # Internal: Piper synthesis
    # ------------------------------------------------------------------

    def _ensure_voice(self):
        """Load the Piper voice once and keep it in-process.

        Returns the loaded voice (any object exposing the pyttsx3-style
        synthesize API) or ``None`` when piper is unavailable or the model
        cannot be loaded.  Never raises.
        """
        if self._voice_loaded:
            return self._voice
        self._voice_loaded = True
        try:
            from piper import PiperVoice  # type: ignore[import-untyped]
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "Piper: 'piper-tts' package not installed (%s) — falling back",
                exc,
            )
            self._voice = None
            return None
        try:
            self._voice = PiperVoice.load(str(self._model_path))
            logger.info("Piper: voice model loaded (%s)", self._model_path.name)
        except Exception as exc:  # noqa: BLE001
            logger.error(
                "Piper: failed to load voice model %s: %s",
                self._model_path, exc, exc_info=True,
            )
            self._voice = None
        return self._voice

    @staticmethod
    def _synthesize_pcm(voice: Any, text: str) -> tuple[bytes, int]:
        """Synthesise *text* and return ``(pcm_bytes, sample_rate)``.

        Adapts to the two Piper API shapes seen in the wild:

         1. ``voice.synthesize(text) -> (audio: np.ndarray, sample_rate)``
            (piper-tts >= 1.2)
         2. ``voice.synthesize_stream_raw(text)`` yielding int16 chunks
            (older piper): the chunks are concatenated into one PCM byte
            string at the model's sample rate.
        """
        # Preferred: newer piper.synthesize returns (audio, sample_rate).
        result = voice.synthesize(text)
        if isinstance(result, tuple) and len(result) == 2:
            audio, sample_rate = result
            return audio.tobytes(), int(sample_rate)

        # Fallback: stream raw int16 chunks.
        chunks = list(voice.synthesize_stream_raw(text))
        pcm = b"".join(chunk.tobytes() for chunk in chunks)
        config = getattr(voice, "config", None)
        sample_rate = int(
            getattr(config, "sample_rate", 0) or _DEFAULT_SAMPLE_RATE
        )
        return pcm, sample_rate

    # ------------------------------------------------------------------
    # Internal: diagnostics
    # ------------------------------------------------------------------

    def _warn_model_missing(self) -> None:
        logger.warning(
            "Piper voice model not found at %s — run: "
            "python -m piper.download_voices %s",
            self._model_path, self._voice_name,
        )