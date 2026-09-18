"""
voice/elevenlabs_provider.py

Real-time ElevenLabs text-to-speech provider.

Downloads audio from the ElevenLabs API and plays it through a shared
VoicePlayer instance for low-latency, interruptible, in-process audio
playback.  No external media player windows.

Supports:
  - PCM output (raw audio, no decode needed)
  - MP3 output with optional pydub-based decode
  - Stream endpoint for lower latency
  - Stop / pause / resume via VoicePlayer
  - Retry on transient failure
  - Comprehensive logging
"""

from __future__ import annotations

import json
import logging
import queue
import threading
import time
import urllib.error
import urllib.request
from socket import timeout as SocketTimeout
from typing import Any

from config.settings import settings
from monitoring.turn_trace import mark as turn_mark
from voice.player import VoicePlayer
from voice.provider import VoiceProvider

logger = logging.getLogger(__name__)

ELEVENLABS_URL = "https://api.elevenlabs.io/v1/text-to-speech"
_REQUEST_TIMEOUT = 30
_MAX_RETRIES = 1

# Streaming pump bounds (FIX 1).  The pump thread moves HTTP chunks into a
# bounded queue so playback starts after the first chunk while memory stays
# capped (~32 x 32 KiB ~= 1 MiB, ~23 s of audio) — still streaming, never a
# full-audio buffer.
_PUMP_QUEUE_SIZE = 32
_PUMP_CHUNK_BYTES = 32768
_FIRST_BYTE_TIMEOUT = 10.0

# Sentinel pushed when the pump finishes or fails (never yielded downstream).
_PUMP_DONE = object()

# Supported PCM output formats (raw audio, no decode needed)
_PCM_FORMATS: dict[str, tuple[int, int]] = {
    "pcm_8000": (8000, 1),
    "pcm_16000": (16000, 1),
    "pcm_22050": (22050, 1),
    "pcm_44100": (44100, 1),
}

_DEFAULT_OUTPUT_FORMAT = "pcm_22050"
_DEFAULT_PLAYBACK_FORMAT = (22050, 2, 1)  # sample_rate, sample_width, channels


class ElevenLabsProvider(VoiceProvider):
    """Speak through ElevenLabs using configuration-provided credentials.

    Audio is played through a shared VoicePlayer instance.
    """

    def __init__(
        self,
        api_key: str | None = None,
        voice_id: str | None = None,
        model: str | None = None,
        *,
        stability: float | None = None,
        similarity_boost: float | None = None,
        style: float | None = None,
        speaker_boost: bool | None = None,
        timeout: int = _REQUEST_TIMEOUT,
        output_format: str = _DEFAULT_OUTPUT_FORMAT,
        player: VoicePlayer | None = None,
    ) -> None:
        self._api_key = (
            api_key if api_key is not None else settings.elevenlabs_api_key
        )
        self._voice_id = (
            voice_id if voice_id is not None else settings.voice_id
        )
        self._model = (
            model if model is not None else settings.voice_model
        )
        self._stability = (
            stability if stability is not None else settings.voice_stability
        )
        self._similarity_boost = (
            similarity_boost
            if similarity_boost is not None
            else settings.voice_similarity
        )
        self._style = (
            style if style is not None else settings.voice_style
        )
        self._speaker_boost = (
            speaker_boost
            if speaker_boost is not None
            else settings.voice_speaker_boost
        )
        self._timeout = timeout
        self._output_format = output_format
        self._player = player or VoicePlayer()
        self._stats: dict[str, Any] = {}
        # Active streaming download (response, stop-event), if any.  Owned
        # by the pump thread; cancelled from stop() on barge-in (FIX 1).
        self._active_stream: tuple[Any, threading.Event] | None = None

        # FIX-QUOTA-NO-RETRY: once a 401/429 (quota/auth) is observed, treat
        # the provider as unavailable for the rest of the process — no retries,
        # so the VoiceManager falls back to Piper/system immediately.
        self._quota_blocked = False

        # Validate configuration
        self._validate_config()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def speak(self, text: str) -> bool:
        """Synthesise text via ElevenLabs and play through VoicePlayer.

        Returns True when the API request was accepted. Audio plays
        asynchronously on the VoicePlayer's background thread.
        """
        if not isinstance(text, str) or not text.strip():
            return False
        if not self._api_key:
            logger.error("ElevenLabs: speak aborted — no API key configured")
            return False
        if not self._voice_id:
            logger.error("ElevenLabs: speak aborted — no Voice ID configured")
            return False
        if self._quota_blocked:
            logger.warning("ElevenLabs: speak aborted — quota/auth already blocked")
            return False

        payload = text.strip()
        request = self._build_request(payload)
        last_error: Exception | None = None

        for attempt in range(1 + _MAX_RETRIES):
            logger.info(
                "ElevenLabs: request attempt %d/%d (voice=%s, model=%s, format=%s, %d chars)",
                attempt + 1, 1 + _MAX_RETRIES,
                self._voice_id, self._model, self._output_format,
                len(payload),
            )

            start = time.monotonic()
            try:
                response = urllib.request.urlopen(request, timeout=self._timeout)
                status = response.status
                content_type = response.headers.get("Content-Type", "")
                # VOICE-FIX: streaming responses are owned by the pump until
                # playback consumption ends.  Do not use a surrounding
                # context manager here: it would close the response as soon
                # as _play_pcm_stream returns, before the player reads it.
                is_pcm_stream = self._output_format in _PCM_FORMATS or any(
                    fmt in content_type for fmt in (
                        "audio/pcm", "audio/L16", "audio/l16",
                        "audio/raw", "audio/x-raw",
                    )
                )
                if is_pcm_stream:
                    return self._play_pcm_stream(response, start, content_type)
                try:
                    audio_data = response.read()
                finally:
                    response.close()
            except urllib.error.HTTPError as exc:
                elapsed = (time.monotonic() - start) * 1000
                try:
                    body = exc.read().decode("utf-8", errors="replace")
                except Exception:
                    body = "<unreadable>"
                logger.warning(
                    "ElevenLabs: HTTP %d (attempt %d, %.0f ms): %s | body: %s",
                    exc.code, attempt + 1, elapsed, exc, body,
                )
                last_error = exc
                # FIX-QUOTA-NO-RETRY: 401 (invalid/quota key) and 429 (quota
                # exceeded) are NOT transient — retrying only stacks silent
                # dead seconds onto every spoken line.  Fail immediately so
                # the VoiceManager fallback chain (Piper -> system) takes over
                # without delay.
                if exc.code in (401, 429):
                    self._quota_blocked = True
                    logger.warning(
                        "ElevenLabs: HTTP %d is a permanent quota/auth error — "
                        "not retrying, switching provider (elapsed %.0f ms)",
                        exc.code, elapsed,
                    )
                    return False
                if attempt < _MAX_RETRIES:
                    logger.info("ElevenLabs: retrying...")
                    time.sleep(0.5)
                continue
            except (
                urllib.error.URLError,
                SocketTimeout,
                TimeoutError,
                OSError,
            ) as exc:
                elapsed = (time.monotonic() - start) * 1000
                logger.warning(
                    "ElevenLabs: request failed (attempt %d, %.0f ms): %s",
                    attempt + 1, elapsed, exc,
                )
                last_error = exc
                if attempt < _MAX_RETRIES:
                    logger.info("ElevenLabs: retrying...")
                    time.sleep(0.5)
                continue

            elapsed = (time.monotonic() - start) * 1000
            self._stats["last_request_ms"] = elapsed

            if status != 200:
                logger.error(
                    "ElevenLabs: HTTP %d (attempt %d, %.0f ms)",
                    status, attempt + 1, elapsed,
                )
                last_error = RuntimeError(f"HTTP {status}")
                if attempt < _MAX_RETRIES:
                    continue
                return False

            if not audio_data:
                logger.error("ElevenLabs: empty response (attempt %d)", attempt + 1)
                last_error = RuntimeError("empty response")
                if attempt < _MAX_RETRIES:
                    continue
                return False

            logger.info(
                "ElevenLabs: API OK (%d bytes, %.0f ms, Content-Type: %s)",
                len(audio_data), elapsed, content_type,
            )

            # Determine if the response is PCM (raw) or MP3
            is_pcm = any(fmt in content_type for fmt in (
                "audio/pcm", "audio/L16", "audio/l16",
                "audio/raw", "audio/x-raw",
            )) or self._output_format in _PCM_FORMATS

            if is_pcm:
                sample_rate, channels = _PCM_FORMATS.get(
                    self._output_format, (22050, 1)
                )
                self._player.play(
                    audio_data,
                    sample_rate=sample_rate,
                    sample_width=2,
                    channels=channels,
                )
                logger.info(
                    "ElevenLabs: playing PCM (%d Hz, %d ch, %d bytes)",
                    sample_rate, channels, len(audio_data),
                )
                return True

            # MP3 response — try to decode and play
            return self._play_mp3(audio_data, payload)

        logger.error(
            "ElevenLabs: all %d attempts failed: %s",
            1 + _MAX_RETRIES, last_error,
        )
        return False

    def _play_pcm_stream(self, response, start: float, content_type: str) -> bool:
        """Play a PCM HTTP response incrementally as chunks arrive.

        FIX 1: the old code handed the player worker a lazy generator over
        the live HTTP response and returned immediately — the ``with``
        block then closed the response before the first read, so playback
        died with 0 bytes consumed while success was reported.  Now a pump
        thread owns the response lifetime (it closes it only after EOF /
        error / cancellation), playback starts after the first real chunk,
        and ``False`` is returned when no audio was ever consumed.
        """
        sample_rate, channels = _PCM_FORMATS.get(
            self._output_format, (22050, 1)
        )
        chunks: queue.Queue = queue.Queue(maxsize=_PUMP_QUEUE_SIZE)
        pump_error: list[str] = []
        pump_stop = threading.Event()

        def _pump() -> None:
            try:
                while not pump_stop.is_set():
                    try:
                        piece = response.read(_PUMP_CHUNK_BYTES)
                    except Exception as exc:
                        pump_error.append(f"read failed: {exc}")
                        break
                    if not piece:
                        break
                    # Bounded put with stop checks so cancellation never wedges.
                    while not pump_stop.is_set():
                        try:
                            chunks.put(piece, timeout=0.1)
                            break
                        except queue.Full:
                            continue
            finally:
                try:
                    chunks.put(_PUMP_DONE, timeout=1.0)
                except queue.Full:
                    # Consumer gone (cancelled) — drop the sentinel; the
                    # generator below also terminates on pump_stop.
                    pass
                try:
                    response.close()
                except Exception:
                    pass

        # Track the active stream so stop() can cancel a download whose
        # playback was interrupted (barge-in must not leak sockets/threads).
        # Cleared below when this stream drains normally; only cleared if
        # still ours so a newer utterance is never disturbed (FIX 3).
        active_token = (response, pump_stop)
        self._active_stream = active_token
        pump = threading.Thread(target=_pump, name="elevenlabs-pump", daemon=True)
        pump.start()
        try:
            # Gate success on real audio: wait (bounded) for the first chunk.
            # This is what makes "streaming started" an honest statement.
            first: Any = None
            deadline = time.monotonic() + _FIRST_BYTE_TIMEOUT
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    break
                try:
                    first = chunks.get(timeout=min(remaining, 0.5))
                    break
                except queue.Empty:
                    if pump_stop.is_set() or not pump.is_alive():
                        break
                    continue
            if first is None or first is _PUMP_DONE:
                if pump_error:
                    logger.error(
                        "ElevenLabs: stream failed before first audio: %s",
                        pump_error[0],
                    )
                else:
                    logger.error("ElevenLabs: empty audio stream (no PCM chunks)")
                pump_stop.set()
                if self._active_stream is active_token:
                    self._active_stream = None
                return False

            first_at = time.monotonic()
            turn_mark(
                "TTS_STREAM_START",
                provider="elevenlabs",
                bytes=len(first),
                elapsed_ms=round((first_at - start) * 1000),
            )
            logger.info(
                "ElevenLabs: first audio chunk (%d bytes, %.0f ms "
                "to first byte, Content-Type: %s)",
                len(first), (first_at - start) * 1000, content_type,
            )

            def _stream_chunks():
                try:
                    yield first
                    while True:
                        try:
                            piece = chunks.get(timeout=0.5)
                        except queue.Empty:
                            if pump_stop.is_set() or not pump.is_alive():
                                if pump_error:
                                    raise RuntimeError(pump_error[0])
                                return
                            continue
                        if piece is _PUMP_DONE or piece is None:
                            if pump_error:
                                raise RuntimeError(pump_error[0])
                            return
                        yield piece
                finally:
                    # Drained (or abandoned): release our tracking slot only
                    # if a newer utterance hasn't claimed it (FIX 3).
                    if self._active_stream is active_token:
                        self._active_stream = None

            self._player.play_stream(
                _stream_chunks(), sample_rate=sample_rate,
                sample_width=2, channels=channels,
            )
            elapsed = (time.monotonic() - start) * 1000
            self._stats["last_request_ms"] = elapsed
            logger.info(
                "ElevenLabs: streaming PCM playback started "
                "(%d Hz, %d ch, headers %.0f ms)",
                sample_rate, channels, elapsed,
            )
            return True
        except Exception as exc:
            logger.error("ElevenLabs: streaming setup failed: %s", exc)
            pump_stop.set()
            if self._active_stream is active_token:
                self._active_stream = None
            return False

    def stop(self) -> None:
        """Stop playback immediately, including any in-flight download."""
        active, self._active_stream = self._active_stream, None
        if active is not None:
            response, pump_stop = active
            try:
                pump_stop.set()
            except Exception:
                pass
            try:
                response.close()
            except Exception:
                pass
        self._player.stop()
        logger.debug("ElevenLabs: stopped via player")

    @property
    def is_playing(self) -> bool:
        """True when audio is currently playing."""
        return self._player.is_playing

    def pause(self) -> None:
        """Pause playback."""
        self._player.pause()
        logger.debug("ElevenLabs: paused")

    def resume(self) -> None:
        """Resume paused playback."""
        self._player.resume()
        logger.debug("ElevenLabs: resumed")

    @property
    def player(self) -> VoicePlayer:
        """The shared VoicePlayer instance used for playback."""
        return self._player

    @property
    def stats(self) -> dict[str, Any]:
        """Return diagnostic statistics."""
        return dict(self._stats)

    # ------------------------------------------------------------------
    # Internal: request building
    # ------------------------------------------------------------------

    def _build_request(self, text: str) -> urllib.request.Request:
        """Build a streaming HTTP request with PCM output format."""
        body_fields: dict[str, Any] = {
            "text": text,
            "model_id": self._model,
        }

        voice_settings: dict[str, Any] = {}
        if self._stability is not None:
            voice_settings["stability"] = self._stability
        if self._similarity_boost is not None:
            voice_settings["similarity_boost"] = self._similarity_boost
        if self._style is not None:
            voice_settings["style"] = self._style
        if self._speaker_boost is not None:
            voice_settings["use_speaker_boost"] = self._speaker_boost
        if voice_settings:
            body_fields["voice_settings"] = voice_settings

        body = json.dumps(body_fields).encode("utf-8")

        # Use the streaming endpoint for lower latency
        url = f"{ELEVENLABS_URL}/{self._voice_id}/stream"

        # Request PCM format
        accept = (
            f"audio/pcm;rate={_PCM_FORMATS.get(self._output_format, (22050,))[0]}"
            if self._output_format in _PCM_FORMATS
            else "audio/mpeg"
        )

        return urllib.request.Request(
            f"{url}?output_format={self._output_format}",
            data=body,
            headers={
                "Accept": accept,
                "Content-Type": "application/json",
                "xi-api-key": self._api_key or "",
            },
            method="POST",
        )

    # ------------------------------------------------------------------
    # Internal: MP3 playback
    # ------------------------------------------------------------------

    def _play_mp3(self, mp3_data: bytes, text: str) -> bool:
        """Decode MP3 bytes and play through VoicePlayer.

        Tries multiple decode backends, falling forward on failure.
        """
        pcm_data = self._decode_mp3(mp3_data)
        if pcm_data:
            pcm, sample_rate = pcm_data
            self._player.play(
                pcm, sample_rate=sample_rate,
                sample_width=2, channels=1,
            )
            return True

        # Last resort: write temp WAV and play via Windows
        logger.warning("ElevenLabs: no MP3 decoder available, using temp file fallback")
        return self._play_mp3_fallback(mp3_data)

    @staticmethod
    def _decode_mp3(mp3_data: bytes) -> tuple[bytes, int] | None:
        """Decode MP3 data to 16-bit mono PCM.

        Returns (pcm_bytes, sample_rate) or None if no decoder available.
        """
        # Backend 1: pydub (requires ffmpeg)
        try:
            import io as _io
            from pydub import AudioSegment  # type: ignore[import-untyped]

            seg: AudioSegment = AudioSegment.from_mp3(_io.BytesIO(mp3_data))
            seg = seg.set_frame_rate(22050).set_channels(1).set_sample_width(2)
            pcm = seg.raw_data
            logger.info(
                "ElevenLabs: decoded MP3 via pydub (%d bytes, %d Hz)",
                len(pcm), seg.frame_rate,
            )
            return pcm, seg.frame_rate
        except ImportError:
            logger.debug("ElevenLabs: pydub not available for MP3 decode")
        except Exception as exc:
            logger.debug("ElevenLabs: pydub decode failed: %s", exc)

        return None

    @staticmethod
    def _play_mp3_fallback(mp3_data: bytes) -> bool:
        """Fallback: write MP3 to temp file, play via winsound."""
        import tempfile
        import winsound

        try:
            with tempfile.NamedTemporaryFile(
                delete=False, suffix=".wav"
            ) as tmp:
                tmp.write(mp3_data)
                path = tmp.name
            # This likely won't work for MP3 but is a last resort
            winsound.PlaySound(path, winsound.SND_FILENAME | winsound.SND_ASYNC)
            logger.warning("ElevenLabs: temp file fallback (may not support MP3)")
            return True
        except Exception as exc:
            logger.error("ElevenLabs: fallback playback failed: %s", exc)
            return False

    # ------------------------------------------------------------------
    # Internal: validation
    # ------------------------------------------------------------------

    def _validate_config(self) -> None:
        """Log configuration diagnostics."""
        if not self._api_key:
            logger.error("ElevenLabs: ELEVENLABS_API_KEY is not configured")
        if not self._voice_id:
            logger.error("ElevenLabs: VOICE_ID is not configured")
        logger.info(
            "ElevenLabs: configured (voice=%s, model=%s, format=%s, "
            "stability=%s, similarity=%s, style=%s, boost=%s)",
            self._voice_id or "(none)",
            self._model,
            self._output_format,
            self._stability,
            self._similarity_boost,
            self._style,
            self._speaker_boost,
        )
