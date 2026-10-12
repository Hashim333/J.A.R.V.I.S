"""
voice/player.py

Real-time audio playback component using PyAudio.

Runs on a dedicated worker thread so the main application never blocks.
Supports stop(), pause(), resume(), and is_playing.

Streaming playback (``play_stream``) pre-buffers a small jitter window and
then applies **backpressure** to the producer: when the buffer is full the
producer waits, and audio is never discarded.  Dropping PCM mid-stream is
audible as clipping, stutter and amplifier-like distortion, so the buffer is
bounded by capacity, never by throwing data away.

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
from collections import deque
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
_MAX_JITTER_BUFFER_MS = 2000  # Max queue depth; the producer BLOCKS here

# Output block size for streaming playback.  One _CHUNK_SIZE frame of audio
# (46 ms at 22050 Hz) keeps latency low and keeps the amount of audio that
# can still be sitting in the device buffer small.
_STREAM_FRAMES_PER_BUFFER = _CHUNK_SIZE

# On natural completion the device still holds audio it has accepted but not
# yet played.  Closing the stream at that moment cuts the last syllable off.
# Host APIs queue two to three device buffers, so drain that many before
# closing.  This is a bounded, format-derived drain applied ONLY to natural
# completion — an explicit stop() (barge-in) never waits.
_DRAIN_BUFFERS = 3
_MAX_DRAIN_SECONDS = 0.30

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
        # Diagnostic counters (see the stream summary log line).
        self.last_play_received = 0
        self.last_underruns = 0
        self.last_play_max_gap_ms = 0.0
        self.last_cancel_reason: str | None = None
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

        self.stop(reason="superseded")
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
        self.stop(reason="superseded")
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
            "VoicePlayer: started streaming playback (%d Hz, %d-bit, %d ch, "
            "jitter=%d ms)",
            sample_rate, sample_width * 8, channels, _JITTER_BUFFER_MS,
        )

    def _reset_play_result(self) -> None:
        """Clear result accounting for a new playback generation."""
        self.last_play_bytes = 0
        self.last_play_seconds = 0.0
        self.last_play_error = None
        self.last_play_received = 0
        self.last_underruns = 0
        self.last_play_max_gap_ms = 0.0
        self.last_cancel_reason = None

    def _record_play_result(
        self,
        offset: int,
        error: str | None,
        received: int | None = None,
        underruns: int | None = None,
        max_gap_ms: float | None = None,
    ) -> None:
        """Record measured playback outcome (actual bytes written)."""
        self.last_play_bytes = offset
        denom = self._sample_rate * self._sample_width * self._channels
        self.last_play_seconds = offset / denom if denom else 0.0
        self.last_play_error = error
        if received is not None:
            self.last_play_received = received
        if underruns is not None:
            self.last_underruns = underruns
        if max_gap_ms is not None:
            self.last_play_max_gap_ms = max_gap_ms

    def _byte_rate(self) -> int:
        """Bytes per second at the current playback format."""
        return max(
            1, self._sample_rate * self._sample_width * self._channels,
        )

    def _device_drain_seconds(self) -> float:
        """Bounded wait for the output buffer to empty (natural end only).

        The device holds up to ``frames_per_buffer`` frames it has accepted
        but not yet played; closing the stream discards them, which is audible
        as the final syllable being cut off.  Host APIs queue more than one
        device buffer, so allow a few.  Explicit stop() never waits — barge-in
        must remain immediate.
        """
        rate = float(self._sample_rate or _DEFAULT_SAMPLE_RATE)
        return min(_MAX_DRAIN_SECONDS, (_DRAIN_BUFFERS * _STREAM_FRAMES_PER_BUFFER) / rate)

    def _begin_generation(self) -> threading.Event:
        """Create an isolated cancellation token for the new generation."""
        self._pause_event.clear()
        stop_event = threading.Event()
        with self._lock:
            self._generation_stop_events[self._generation] = stop_event
        self._stop_event = stop_event
        return stop_event

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
        received: int | None = None,
        underruns: int | None = None,
        max_gap_ms: float | None = None,
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
        self._record_play_result(
            offset, error, received=received, underruns=underruns,
            max_gap_ms=max_gap_ms,
        )
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
        return (byte_count / self._byte_rate()) * 1000.0

    # ------------------------------------------------------------------
    # Internal workers
    # ------------------------------------------------------------------

    def _play_stream_worker(self, chunks, stop_event: threading.Event) -> None:
        """Stream PCM to the device, paced by backpressure rather than drops."""
        gen = self._generation
        stream = None
        try:
            self._ensure_pyaudio()
            stream = self._pyaudio.open(
                format=_PA_FORMAT,
                channels=self._channels,
                rate=self._sample_rate,
                output=True,
                frames_per_buffer=_STREAM_FRAMES_PER_BUFFER,
            )
        except Exception as exc:
            logger.error("VoicePlayer: failed to open audio stream: %s", exc)
            self._finish_generation(gen, 0, f"open failed: {exc}", stop_event)
            return
        with self._lock:
            self._stream = stream
            self._stream_gen = gen

        bytes_per_second = self._byte_rate()
        # PyAudio rejects a partial frame ("not a whole number of frames"), so
        # every write must cover a whole number of sample frames.  An
        # incomplete frame is carried into the next write rather than aborting
        # playback mid-utterance.
        frame_bytes = max(1, self._sample_width * self._channels)
        jitter_target_bytes = int(bytes_per_second * (_JITTER_BUFFER_MS / 1000.0))

        # Bounded queue.  The pump blocks when it is full (backpressure);
        # it must NEVER discard audio — a dropped 23 ms slice in the middle
        # of an utterance is an audible click/drop-out.
        capacity_chunks = max(
            4,
            int(
                (_MAX_JITTER_BUFFER_MS / 1000.0) * bytes_per_second / _CHUNK_SIZE
            ),
        )
        jitter_queue: queue.Queue[bytes] = queue.Queue(maxsize=capacity_chunks)

        offset = 0
        error: str | None = None
        underrun_count = 0
        received = 0
        playback_started = False
        last_write_time: float | None = None
        max_gap_ms = 0.0
        source_error: list[str] = []
        pump_thread: threading.Thread | None = None
        pending: deque[bytes] = deque()
        source_done = False
        write_carry = b""

        def _pump() -> None:
            nonlocal received
            try:
                for piece in chunks:
                    if stop_event.is_set() or not piece:
                        continue
                    # Hand over in _CHUNK_SIZE slices so stop() stays
                    # responsive and the queue stays granular.
                    for i in range(0, len(piece), _CHUNK_SIZE):
                        if stop_event.is_set():
                            break
                        sub = piece[i:i + _CHUNK_SIZE]
                        # Backpressure, not discarding: wait for room.
                        while not stop_event.is_set():
                            try:
                                jitter_queue.put(sub, timeout=0.05)
                                break
                            except queue.Full:
                                continue
                        if stop_event.is_set():
                            break
                        received += len(sub)
                    if stop_event.is_set():
                        break
            except Exception as exc:
                # The chunk source (HTTP stream / generator) failed mid-
                # stream.  This used to escape the pump thread and vanish
                # into threading.excepthook: no EOS was sent, no error was
                # recorded, and the playback was reported as a clean
                # finish, so the provider looked successful.
                source_error.append(f"source failed: {exc}")
                logger.error("VoicePlayer: chunk source failed: %s", exc)
            finally:
                # Always signal end of stream so the playback loop cannot
                # spin writing silence until stop().
                while not stop_event.is_set():
                    try:
                        jitter_queue.put(b"", timeout=0.05)
                        break
                    except queue.Full:
                        continue

        try:
            pump_thread = threading.Thread(
                target=_pump, name="jitter-pump", daemon=True,
            )
            pump_thread.start()

            # Jitter buffer fill: pull chunks until the target (~400 ms) or the
            # end of the stream is reached.  The pulled chunks are KEPT, in
            # order, in ``pending`` and drained by the playback loop below.
            # The previous version discarded everything it had pulled whenever
            # the stream ended before the target was reached, so any reply
            # shorter than ~400 ms of audio played nothing at all — and the
            # resulting zero-byte accounting then looked like a provider
            # failure (triggering an unnecessary failover / re-speak).
            #
            # ``buffered`` is owned by THIS thread.  The previous version's
            # shared counter was incremented by both threads for the same
            # bytes, so the fill target was reached with roughly half the real
            # audio buffered.
            buffered = 0
            while not playback_started and not stop_event.is_set():
                try:
                    piece = jitter_queue.get(timeout=0.1)
                except queue.Empty:
                    continue
                if piece == b"":  # EOS before playback started
                    source_done = True
                    break
                pending.append(piece)
                buffered += len(piece)
                if buffered >= jitter_target_bytes:
                    break
            playback_started = True

            if self.on_playback_started is not None:
                try:
                    self.on_playback_started()
                except Exception as exc:
                    logger.warning("playback_started callback failed: %s", exc)
            if pending:
                logger.debug(
                    "VoicePlayer: streaming started with %.0f ms buffered "
                    "(target %d ms)",
                    self._bytes_to_ms(buffered), _JITTER_BUFFER_MS,
                )

            try:
                while not stop_event.is_set():
                    # Drain whatever the fill phase already pulled before
                    # touching the live queue, so nothing is reordered or lost.
                    if pending:
                        piece = pending.popleft()
                    elif source_done:
                        break
                    else:
                        try:
                            piece = jitter_queue.get(timeout=0.05)
                        except queue.Empty:
                            # Genuine starvation.  Keep the stream alive with
                            # silence so the device does not glitch, and count
                            # it — this is the only real underrun signal.
                            if playback_started:
                                silence = self._get_silence_chunk(_CHUNK_SIZE)
                                try:
                                    stream.write(silence)
                                    if self.on_chunk_written is not None:
                                        try:
                                            self.on_chunk_written(
                                                silence, self._sample_rate,
                                            )
                                        except Exception:
                                            pass
                                except Exception:
                                    pass
                                underrun_count += 1
                                last_write_time = time.monotonic()
                                if underrun_count % 10 == 1:
                                    logger.warning(
                                        "VoicePlayer: buffer underrun — writing "
                                        "silence (count=%d queue_depth=%d "
                                        "received=%d written=%d)",
                                        underrun_count, jitter_queue.qsize(),
                                        received, offset,
                                    )
                            continue

                    if piece == b"":  # EOS
                        source_done = True
                        break

                    # Write in _CHUNK_SIZE slices so stop() stays responsive.
                    for i in range(0, len(piece), _CHUNK_SIZE):
                        if stop_event.is_set():
                            break
                        if self._pause_event.is_set():
                            self._pause_event.wait(timeout=0.1)
                            continue
                        # Whole sample frames only (see frame_bytes above).
                        buffered = write_carry + piece[i:i + _CHUNK_SIZE]
                        usable = (len(buffered) // frame_bytes) * frame_bytes
                        if usable == 0:
                            write_carry = buffered
                            continue
                        sub, write_carry = buffered[:usable], buffered[usable:]
                        try:
                            now = time.monotonic()
                            if last_write_time is not None:
                                gap_ms = (now - last_write_time) * 1000.0
                                if gap_ms > max_gap_ms:
                                    max_gap_ms = gap_ms
                                expected_ms = (
                                    _CHUNK_SIZE / bytes_per_second
                                ) * 1000.0
                                if gap_ms > expected_ms * 3.0:
                                    logger.debug(
                                        "VoicePlayer: inter-chunk gap %.1f ms "
                                        "(expected ~%.1f ms, queue_depth=%d)",
                                        gap_ms, expected_ms,
                                        jitter_queue.qsize(),
                                    )
                            stream.write(sub)
                            last_write_time = time.monotonic()
                        except Exception as exc:
                            logger.error("VoicePlayer: stream write error: %s", exc)
                            error = f"write failed: {exc}"
                            break
                        offset += len(sub)
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

            # Flush a trailing partial frame (zero-padded) so the final sample
            # is not lost and no write is ever rejected as a partial frame.
            if write_carry and error is None and not stop_event.is_set():
                pad = (-len(write_carry)) % frame_bytes
                tail = write_carry + b"\x00" * pad
                write_carry = b""
                try:
                    stream.write(tail)
                    offset += len(tail)
                    turn_mark("AUDIO_BYTES_WRITTEN", bytes=offset)
                    if self.on_chunk_written is not None:
                        try:
                            self.on_chunk_written(tail, self._sample_rate)
                        except Exception as exc:
                            logger.warning("chunk_written callback failed: %s", exc)
                except Exception as exc:
                    logger.error(
                        "VoicePlayer: stream write error (trailing frame): %s", exc,
                    )
        finally:
            if pump_thread is not None:
                pump_thread.join(timeout=1.0)
            if (
                error is None
                and not stop_event.is_set()
                and offset > 0
            ):
                # Natural end of stream: let the device finish the audio still
                # in its output buffer.  Closing now would cut the last
                # syllable off — the bug the log showed as playback ending
                # while `cancel_all()` raced the stream close.
                time.sleep(self._device_drain_seconds())
            self._close_owned_stream(gen)
            if error is None and source_error:
                # Report the source failure honestly: the manager decides
                # failover from last_play_error / last_play_bytes.
                error = source_error[0]
            seconds = offset / bytes_per_second
            self._finish_generation(
                gen, offset, error, stop_event,
                received=received, underruns=underrun_count,
                max_gap_ms=max_gap_ms,
            )
            turn_mark(
                "TTS_PLAYBACK_COMPLETE",
                bytes=offset,
                error=error,
                interrupted=stop_event.is_set(),
            )
            # One summary line per utterance: what arrived, what was played,
            # any loss, starvation and the worst inter-chunk gap.
            lost = max(0, received - offset)
            logger.info(
                "VoicePlayer: stream summary played=%.2fs received=%d bytes "
                "written=%d bytes lost=%d underruns=%d max_gap=%.1f ms "
                "queue_capacity=%d chunks%s%s",
                seconds, received, offset, lost, underrun_count, max_gap_ms,
                capacity_chunks,
                " [interrupted]" if stop_event.is_set() else "",
                f" [error: {error}]" if error else "",
            )

    def stop(self, reason: str = "explicit") -> None:
        """Stop playback immediately. Thread-safe."""
        playing = self._play_thread is not None and self._play_thread.is_alive()
        if playing:
            # Diagnostic: why this playback ended early.  Barge-in ends a
            # stream by design; normal completion must not.
            self.last_cancel_reason = reason
            logger.info("VoicePlayer: stop requested (reason=%s)", reason)
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
        # Pad the assembled buffer to a whole number of sample frames: the
        # final slice of an odd-length buffer would otherwise be a partial
        # frame, which PyAudio rejects by aborting playback mid-utterance.
        frame_bytes = max(1, self._sample_width * self._channels)
        remainder = len(data) % frame_bytes
        if remainder:
            data = data + b"\x00" * (frame_bytes - remainder)
        offset = 0
        total = len(data)
        error: str | None = None
        underrun_count = 0
        last_write_time = None
        max_gap_ms = 0.0
        bytes_per_second = self._byte_rate()

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
                        expected_ms = (_CHUNK_SIZE / bytes_per_second) * 1000.0
                        if gap_ms > max_gap_ms:
                            max_gap_ms = gap_ms
                        if gap_ms > expected_ms * 3.0:
                            logger.debug(
                                "VoicePlayer: inter-chunk gap %.1f ms "
                                "(expected ~%.1f ms)", gap_ms, expected_ms,
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
            if error is None and not stop_event.is_set() and offset > 0:
                # Let the device drain its buffer so the tail is not cut.
                time.sleep(self._device_drain_seconds())
            self._close_owned_stream(gen)
            elapsed = total / bytes_per_second
            played = offset / bytes_per_second
            self._finish_generation(
                gen, offset, error, stop_event,
                received=total, underruns=underrun_count, max_gap_ms=max_gap_ms,
            )
            turn_mark(
                "TTS_PLAYBACK_COMPLETE",
                bytes=offset,
                error=error,
                interrupted=stop_event.is_set(),
            )
            logger.info(
                "VoicePlayer: finished (played %.1f/%.1f sec, underruns=%d, "
                "max_gap=%.1f ms%s%s)",
                played, elapsed, underrun_count, max_gap_ms,
                " [interrupted]" if stop_event.is_set() else "",
                f" [error: {error}]" if error else "",
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
        self.stop(reason="shutdown")
        if self._pyaudio is not None:
            try:
                self._pyaudio.terminate()
            except Exception:
                pass
            self._pyaudio = None
        logger.info("VoicePlayer: shut down")
