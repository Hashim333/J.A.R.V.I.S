"""
voice/player.py

Real-time audio playback component using PyAudio.

Runs on a dedicated worker thread so the main application never blocks.
Supports stop(), pause(), resume(), and is_playing.

Usage::

    player = VoicePlayer()
    player.play(pcm_data, sample_rate=22050)
    # ...
    player.stop()
    player.pause()
    player.resume()
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Any, Callable

import pyaudio

logger = logging.getLogger(__name__)

_CHUNK_SIZE = 1024
_DEFAULT_SAMPLE_RATE = 22050
_DEFAULT_SAMPLE_WIDTH = 2
_DEFAULT_CHANNELS = 1
_PA_FORMAT = pyaudio.paInt16  # 16-bit PCM


class VoicePlayer:
    """Dedicated audio playback component with stop/pause/resume."""

    def __init__(self) -> None:
        self._pyaudio: pyaudio.PyAudio | None = None
        self._stream: Any = None
        self._play_thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._pause_event = threading.Event()
        self._lock = threading.Lock()
        self._audio_data: bytes = b""
        self._sample_rate: int = _DEFAULT_SAMPLE_RATE
        self._sample_width: int = _DEFAULT_SAMPLE_WIDTH
        self._channels: int = _DEFAULT_CHANNELS
        self.on_playback_started: Callable[[], None] | None = None
        self.on_playback_finished: Callable[[], None] | None = None
        # Echo-reference hook: called with (pcm_chunk, sample_rate) for every
        # chunk written to the speakers, so the full-duplex echo canceller
        # can subtract JARVIS's own voice from the captured microphone.
        self.on_chunk_written: Callable[[bytes, int], None] | None = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def play(
        self,
        audio_data: bytes,
        sample_rate: int = _DEFAULT_SAMPLE_RATE,
        sample_width: int = _DEFAULT_SAMPLE_WIDTH,
        channels: int = _DEFAULT_CHANNELS,
    ) -> None:
        """Play PCM audio data on a background thread.

        If audio is already playing, the current playback is stopped
        and replaced (interrupted).
        """
        if not audio_data:
            logger.warning("VoicePlayer: play() called with empty audio data")
            return

        self.stop()

        self._audio_data = audio_data
        self._sample_rate = sample_rate
        self._sample_width = sample_width
        self._channels = channels
        self._stop_event.clear()
        self._pause_event.clear()

        self._play_thread = threading.Thread(
            target=self._play_worker, daemon=True
        )
        self._play_thread.start()
        logger.info(
            "VoicePlayer: started playback (%d bytes, %d Hz, %d-bit, %d ch)",
            len(audio_data), sample_rate, sample_width * 8, channels,
        )

    def stop(self) -> None:
        """Stop playback immediately. Thread-safe."""
        self._stop_event.set()
        self._pause_event.clear()

        # Wait for the play worker to leave stream.write() BEFORE closing the
        # stream.  Closing a PyAudio stream while another thread is blocked
        # inside write() is a PortAudio thread-safety violation and can
        # deadlock the whole process.
        thread = self._play_thread
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=1.0)

        with self._lock:
            self._close_stream()
            self._audio_data = b""

        self._play_thread = None
        logger.debug("VoicePlayer: stopped")

    def pause(self) -> None:
        """Pause playback. Call resume() to continue."""
        self._pause_event.set()
        logger.debug("VoicePlayer: paused")

    def resume(self) -> None:
        """Resume paused playback."""
        self._pause_event.clear()
        logger.debug("VoicePlayer: resumed")

    @property
    def is_playing(self) -> bool:
        """True if audio is currently playing (or paused)."""
        if self._play_thread is None:
            return False
        return self._play_thread.is_alive()

    # ------------------------------------------------------------------
    # Internal worker
    # ------------------------------------------------------------------

    def _play_worker(self) -> None:
        """Background thread that streams PCM data to PyAudio."""
        stream = None
        try:
            self._ensure_pyaudio()
            stream = self._pyaudio.open(
                format=_PA_FORMAT,
                channels=self._channels,
                rate=self._sample_rate,
                output=True,
                frames_per_buffer=_CHUNK_SIZE,
            )
        except Exception as exc:
            logger.error("VoicePlayer: failed to open audio stream: %s", exc)
            return

        with self._lock:
            self._stream = stream

        data = self._audio_data
        offset = 0
        total = len(data)

        try:
            # Fire playback-started callback — mic mute happens here
            if self.on_playback_started is not None:
                try:
                    self.on_playback_started()
                except Exception as exc:
                    logger.warning("playback_started callback failed: %s", exc)

            while offset < total and not self._stop_event.is_set():
                # Handle pause
                if self._pause_event.is_set():
                    self._pause_event.wait(timeout=0.1)
                    continue

                chunk = data[offset:offset + _CHUNK_SIZE]
                if not chunk:
                    break

                try:
                    stream.write(chunk)
                except Exception as exc:
                    logger.error("VoicePlayer: stream write error: %s", exc)
                    break

                offset += len(chunk)

                if self.on_chunk_written is not None:
                    try:
                        self.on_chunk_written(chunk, self._sample_rate)
                    except Exception as exc:
                        logger.warning("chunk_written callback failed: %s", exc)

        finally:
            self._close_stream()
            elapsed = total / (self._sample_rate * self._sample_width * self._channels)
            played = offset / (self._sample_rate * self._sample_width * self._channels)
            logger.info(
                "VoicePlayer: finished (played %.1f/%.1f sec%s)",
                played, elapsed,
                " [interrupted]" if self._stop_event.is_set() else "",
            )
            # Cooldown then fire playback-finished callback — mic unmute
            if self.on_playback_finished is not None:
                if not self._stop_event.is_set():
                    time.sleep(0.2)
                try:
                    self.on_playback_finished()
                except Exception as exc:
                    logger.warning("playback_finished callback failed: %s", exc)

    def _ensure_pyaudio(self) -> None:
        if self._pyaudio is None:
            self._pyaudio = pyaudio.PyAudio()

    def _close_stream(self) -> None:
        """Safely close and release the audio stream."""
        stream = getattr(self, "_stream", None)
        if stream is not None:
            try:
                if stream.is_active():
                    stream.stop_stream()
                stream.close()
            except Exception:
                pass
            self._stream = None

    def shutdown(self) -> None:
        """Release all resources. Call once at program exit."""
        self.stop()
        if self._pyaudio is not None:
            try:
                self._pyaudio.terminate()
            except Exception:
                pass
            self._pyaudio = None
        logger.info("VoicePlayer: shut down")
