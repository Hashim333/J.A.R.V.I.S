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
import queue
import threading
import time
from typing import Any, Callable

import pyaudio

from monitoring.turn_trace import mark as turn_mark

logger = logging.getLogger(__name__)

_CHUNK_SIZE = 1024
_DEFAULT_SAMPLE_RATE = 22050
_DEFAULT_SAMPLE_WIDTH = 2
_DEFAULT_CHANNELS = 1
_PA_FORMAT = pyaudio.paInt16  # 16-bit PCM

# Jitter buffer settings
_JITTER_BUFFER_MS = 400  # Buffer 400ms before starting playback
_MAX_JITTER_BUFFER_MS = 2000  # Max buffer to prevent unbounded growth
_SILENCE_CHUNK_CACHE = {}  # Cache silence chunks by (sample_rate, sample_width, channels, chunk_size)


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
        # Playback generation: bumped on every play()/play_stream() so a
        # late callback or stream-close from a superseded worker can never
        # touch state owned by the current playback (FIX 1 + FIX 3).
        self._generation = 0
        self._generation_stop_events: dict[int, threading.Event] = {}
        # Which generation owns self._stream (set under _lock next to it).
        self._stream_gen: int | None = None
        # Result accounting for the most recent playback, measured from
        # actual bytes written to the device (FIX 1: never report success
        # when nothing was consumed).
        self.last_play_bytes = 0
        self.last_play_seconds = 0.0
        self.last_play_error: str | None = None
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
        self._generation += 1
        self._reset_play_result()

        self._audio_data = audio_data
        self._sample_rate = sample_rate
        self._sample_width = sample_width
        self._channels = channels
        stop_event = self._begin_generation()

        self._play_thread = threading.Thread(
            target=self._play_worker, args=(stop_event,), daemon=True
        )
        self._play_thread.start()
        logger.info(
            "VoicePlayer: started playback (%d bytes, %d Hz, %d-bit, %d ch)",
            len(audio_data), sample_rate, sample_width * 8, channels,
        )

    def play_stream(
        self,
        chunks,
        sample_rate: int = _DEFAULT_SAMPLE_RATE,
        sample_width: int = _DEFAULT_SAMPLE_WIDTH,
        channels: int = _DEFAULT_CHANNELS,
    ) -> None:
        """Play PCM *chunks* (an iterable) as they arrive, on one thread.

        VOICE-FIX: lets the ElevenLabs provider start audible playback from
        the first HTTP chunk instead of waiting for the full download —
        time-to-first-audio drops without changing voice quality (same PCM
        bytes, same player, just written earlier).  Stoppable mid-stream
        via stop() for barge-in.
        """
        if chunks is None:
            return
        self.stop()
        self._generation += 1
        self._reset_play_result()
        self._sample_rate = sample_rate
        self._sample_width = sample_width
        self._channels = channels
        stop_event = self._begin_generation()
        # Materialise the iterable reference; the worker pulls lazily.
        self._audio_data = b""
        self._play_thread = threading.Thread(
            target=self._play_stream_worker, args=(chunks, stop_event), daemon=True
        )
        self._play_thread.start()
        logger.info(
            "VoicePlayer: started streaming playback (%d Hz, %d-bit, %d ch)",
            sample_rate, sample_width * 8, channels,
        )

    def _reset_play_result(self) -> None:
        """Clear result accounting for a new playback generation."""
        self.last_play_bytes = 0
        self.last_play_seconds = 0.0
        self.last_play_error = None

    def _begin_generation(self) -> threading.Event:
        """Create an isolated cancellation token for the new generation."""
        self._pause_event.clear()
        stop_event = threading.Event()
        with self._lock:
            self._generation_stop_events[self._generation] = stop_event
        self._stop_event = stop_event
        return stop_event

    def _record_play_result(self, offset: int, error: str | None) -> None:
        """Record measured playback outcome (actual bytes written)."""
        self.last_play_bytes = offset
        denom = self._sample_rate * self._sample_width * self._channels
        self.last_play_seconds = offset / denom if denom else 0.0
        self.last_play_error = error

    def _close_owned_stream(self, gen: int) -> None:
        """Close the device stream only if still owned by generation *gen*.

        A superseded worker that outlives stop()'s join must never close a
        newer playback's stream (FIX 3).
        """
        with self._lock:
            if self._stream_gen != gen:
                return
            stream, self._stream, self._stream_gen = self._stream, None, None
        if stream is not None:
            try:
                if stream.is_active():
                    stream.stop_stream()
                stream.close()
            except Exception:
                pass

    def _finish_generation(
        self,
        gen: int,
        offset: int,
        error: str | None,
        stop_event: threading.Event | None = None,
    ) -> None:
        """Record the result and fire completion only for the live generation.

        Late callbacks from a cancelled/superseded worker are dropped so
        they cannot unmute the mic, feed stale echo reference, or flip
        playback state belonging to newer audio (FIX 1 + FIX 3).
        """
        if gen != self._generation:
            logger.debug(
                "VoicePlayer: dropping stale completion (gen=%d current=%d)",
                gen, self._generation,
            )
            with self._lock:
                self._generation_stop_events.pop(gen, None)
            return
        self._record_play_result(offset, error)
        with self._lock:
            self._generation_stop_events.pop(gen, None)
        if self.on_playback_finished is not None:
            try:
                self.on_playback_finished()
            except Exception as exc:
                logger.warning("playback_finished callback failed: %s", exc)

    def _get_silence_chunk(self, chunk_size: int) -> bytes:
        """Get or create a cached silence chunk."""
        key = (self._sample_rate, self._sample_width, self._channels, chunk_size)
        if key not in _SILENCE_CHUNK_CACHE:
            _SILENCE_CHUNK_CACHE[key] = b"\x00" * (chunk_size * self._sample_width * self._channels)
        return _SILENCE_CHUNK_CACHE[key]

    def _bytes_to_ms(self, byte_count: int) -> float:
        """Convert byte count to milliseconds at current format."""
        if self._sample_rate <= 0:
            return 0.0
        return (byte_count / (self._sample_rate * self._sample_width * self._channels)) * 1000.0

    # ------------------------------------------------------------------
    # Internal workers
    # ------------------------------------------------------------------

    def _play_stream_worker(self, chunks, stop_event: threading.Event) -> None:
        gen = self._generation
        stream = None
        try:
            self._ensure_pyaudio()
            stream = self._pyaudio.open(
                format=_PA_FORMAT,
                channels=self._channels,
                rate=self._sample_rate,
                output=True,
                frames_per_buffer=_CHUNK_SIZE * 4,  # Larger output blocksize for stability
            )
        except Exception as exc:
            logger.error("VoicePlayer: failed to open audio stream: %s", exc)
            self._finish_generation(gen, 0, f"open failed: {exc}", stop_event)
            return
        with self._lock:
            self._stream = stream
            self._stream_gen = gen

        # Jitter buffer: queue incoming chunks, start playback after ~400ms buffered
        jitter_queue: queue.Queue[bytes] = queue.Queue()
        jitter_bytes = 0
        jitter_target_bytes = int(self._sample_rate * self._sample_width * self._channels * (_JITTER_BUFFER_MS / 1000.0))
        jitter_max_bytes = int(self._sample_rate * self._sample_width * self._channels * (_MAX_JITTER_BUFFER_MS / 1000.0))
        playback_started = False

        offset = 0
        error: str | None = None
        underrun_count = 0
        last_write_time = None
        try:
            # Start pump thread to fill jitter buffer
            def _pump():
                nonlocal jitter_bytes
                for piece in chunks:
                    if stop_event.is_set() or not piece:
                        continue
                    # Write in _CHUNK_SIZE slices so stop() stays responsive.
                    for i in range(0, len(piece), _CHUNK_SIZE):
                        if stop_event.is_set():
                            break
                        if self._pause_event.is_set():
                            self._pause_event.wait(timeout=0.1)
                        sub = piece[i:i + _CHUNK_SIZE]
                        try:
                            jitter_queue.put(sub, timeout=0.1)
                            jitter_bytes += len(sub)
                            # Cap jitter buffer to prevent unbounded growth
                            if jitter_bytes > jitter_max_bytes:
                                # Drain excess
                                while jitter_bytes > jitter_target_bytes:
                                    try:
                                        excess = jitter_queue.get_nowait()
                                        jitter_bytes -= len(excess)
                                    except queue.Empty:
                                        break
                        except queue.Full:
                            continue
                # Signal end of stream
                jitter_queue.put(b"", timeout=1.0)  # Empty bytes = EOS

            pump_thread = threading.Thread(target=_pump, name="jitter-pump", daemon=True)
            pump_thread.start()

            # Wait for jitter buffer to fill to target
            while not playback_started and not stop_event.is_set():
                try:
                    piece = jitter_queue.get(timeout=0.1)
                    if piece == b"":  # EOS before playback started
                        playback_started = True
                        break
                    jitter_bytes += len(piece)
                    if jitter_bytes >= jitter_target_bytes:
                        playback_started = True
                        # Put it back for the playback loop
                        jitter_queue.put(piece, timeout=0.1)
                        jitter_bytes -= len(piece)
                        break
                except queue.Empty:
                    continue

            if self.on_playback_started is not None:
                try:
                    self.on_playback_started()
                except Exception as exc:
                    logger.warning("playback_started callback failed: %s", exc)

            try:
                while not stop_event.is_set():
                    try:
                        piece = jitter_queue.get(timeout=0.05)
                    except queue.Empty:
                        # Jitter buffer empty - write silence to keep stream alive
                        if playback_started:
                            silence = self._get_silence_chunk(_CHUNK_SIZE)
                            try:
                                stream.write(silence)
                                if self.on_chunk_written is not None:
                                    try:
                                        self.on_chunk_written(silence, self._sample_rate)
                                    except Exception:
                                        pass
                            except Exception:
                                pass
                            underrun_count += 1
                            if underrun_count % 10 == 1:  # Log every 10th underrun
                                logger.warning(
                                    "VoicePlayer: buffer underrun, writing silence (count=%d)",
                                    underrun_count
                                )
                        continue

                    if piece == b"":  # EOS
                        break

                    # Write in _CHUNK_SIZE slices so stop() stays responsive.
                    for i in range(0, len(piece), _CHUNK_SIZE):
                        if stop_event.is_set():
                            break
                        if self._pause_event.is_set():
                            self._pause_event.wait(timeout=0.1)
                            continue
                        sub = piece[i:i + _CHUNK_SIZE]
                        try:
                            now = time.monotonic()
                            if last_write_time is not None:
                                gap_ms = (now - last_write_time) * 1000.0
                                expected_ms = (_CHUNK_SIZE / (self._sample_rate * self._sample_width * self._channels)) * 1000.0
                                if gap_ms > expected_ms * 3.0:  # >3x expected = likely underrun
                                    underrun_count += 1
                                    if underrun_count % 10 == 1:
                                        logger.warning(
                                            "VoicePlayer: buffer underrun detected (gap=%.1f ms, expected~%.1f ms, count=%d)",
                                            gap_ms, expected_ms, underrun_count
                                        )
                            stream.write(sub)
                            last_write_time = time.monotonic()
                        except Exception as exc:
                            logger.error("VoicePlayer: stream write error: %s", exc)
                            error = f"write failed: {exc}"
                            break
                        offset += len(sub)
                        jitter_bytes -= len(sub)
                        turn_mark("AUDIO_BYTES_WRITTEN", bytes=offset)
                        if self.on_chunk_written is not None:
                            try:
                                self.on_chunk_written(sub, self._sample_rate)
                            except Exception as exc:
                                logger.warning("chunk_written callback failed: %s", exc)
                    if error is not None:
                        break
            except Exception as exc:
                logger.error("VoicePlayer: chunk source failed: %s", exc)
                error = f"source failed: {exc}"
        finally:
            pump_thread.join(timeout=0.5)
            self._close_owned_stream(gen)
            seconds = offset / (self._sample_rate * self._sample_width * self._channels)
            if underrun_count:
                logger.warning(
                    "VoicePlayer: streaming finished with %d buffer underrun(s) (played %.1f sec%s%s)",
                    underrun_count, seconds,
                    " [interrupted]" if stop_event.is_set() else "",
                    f" [error: {error}]" if error else "",
                )
            else:
                logger.info(
                    "VoicePlayer: streaming finished (played %.1f sec%s%s)",
                    seconds,
                    " [interrupted]" if stop_event.is_set() else "",
                    f" [error: {error}]" if error else "",
                )
            self._finish_generation(gen, offset, error, stop_event)
            turn_mark(
                "TTS_PLAYBACK_COMPLETE",
                bytes=offset,
                error=error,
                interrupted=stop_event.is_set(),
            )

    def stop(self) -> None:
        """Stop playback immediately. Thread-safe."""
        with self._lock:
            stop_event = self._generation_stop_events.get(self._generation)
        if stop_event is not None:
            stop_event.set()
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

    def _play_worker(self, stop_event: threading.Event) -> None:
        """Background thread that streams PCM data to PyAudio."""
        gen = self._generation
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
            self._finish_generation(gen, 0, f"open failed: {exc}", stop_event)
            return

        with self._lock:
            self._stream = stream
            self._stream_gen = gen

        data = self._audio_data
        offset = 0
        total = len(data)
        error: str | None = None
        underrun_count = 0
        last_write_time = None

        try:
            # Fire playback-started callback — mic mute happens here
            if self.on_playback_started is not None:
                try:
                    self.on_playback_started()
                except Exception as exc:
                    logger.warning("playback_started callback failed: %s", exc)

            while offset < total and not stop_event.is_set():
                # Handle pause
                if self._pause_event.is_set():
                    self._pause_event.wait(timeout=0.1)
                    continue

                chunk = data[offset:offset + _CHUNK_SIZE]
                if not chunk:
                    break

                try:
                    now = time.monotonic()
                    if last_write_time is not None:
                        gap_ms = (now - last_write_time) * 1000.0
                        expected_ms = (_CHUNK_SIZE / (self._sample_rate * self._sample_width * self._channels)) * 1000.0
                        if gap_ms > expected_ms * 3.0:  # >3x expected = likely underrun
                            underrun_count += 1
                            logger.warning(
                                "VoicePlayer: buffer underrun detected (gap=%.1f ms, expected~%.1f ms, count=%d)",
                                gap_ms, expected_ms, underrun_count
                            )
                    stream.write(chunk)
                    last_write_time = time.monotonic()
                except Exception as exc:
                    logger.error("VoicePlayer: stream write error: %s", exc)
                    error = f"write failed: {exc}"
                    break

                offset += len(chunk)
                turn_mark("AUDIO_BYTES_WRITTEN", bytes=offset)

                if self.on_chunk_written is not None:
                    try:
                        self.on_chunk_written(chunk, self._sample_rate)
                    except Exception as exc:
                        logger.warning("chunk_written callback failed: %s", exc)

        finally:
            self._close_owned_stream(gen)
            elapsed = total / (self._sample_rate * self._sample_width * self._channels)
            played = offset / (self._sample_rate * self._sample_width * self._channels)
            if underrun_count:
                logger.warning(
                    "VoicePlayer: finished with %d buffer underrun(s) (played %.1f/%.1f sec%s%s)",
                    underrun_count, played, elapsed,
                    " [interrupted]" if stop_event.is_set() else "",
                    f" [error: {error}]" if error else "",
                )
            else:
                logger.info(
                    "VoicePlayer: finished (played %.1f/%.1f sec%s%s)",
                    played, elapsed,
                    " [interrupted]" if stop_event.is_set() else "",
                    f" [error: {error}]" if error else "",
                )
            # Cooldown then fire playback-finished callback — mic unmute.
            # Generation-guarded so a stale worker cannot unmute/complete
            # newer audio (FIX 3).
            self._finish_generation(gen, offset, error, stop_event)
            turn_mark(
                "TTS_PLAYBACK_COMPLETE",
                bytes=offset,
                error=error,
                interrupted=stop_event.is_set(),
            )

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