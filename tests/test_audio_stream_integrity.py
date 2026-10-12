"""Audio-stream integrity regression tests.

Covers the confirmed glitch: the streaming jitter buffer capped itself by
**discarding** queued PCM.  ``_play_stream_worker``'s pump incremented
``jitter_bytes`` on every enqueue *and* the playback loop incremented it again
on every dequeue (an unsynchronised ``nonlocal`` shared by two threads), so the
counter roughly doubled and the "2000 ms" cap was reached with far less real
audio buffered.  The pump then drained the queue with ``get_nowait()`` and threw
the pieces away — deleting real audio from the middle of the utterance, which
is audible as clipping, stutter and amplifier-like distortion.

No audio hardware: PyAudio and the output stream are faked, and the fake stream
consumes data at real time so producer/consumer scheduling is exercised for
real.
"""
from __future__ import annotations

import threading
import time
import unittest
from unittest.mock import MagicMock, patch

from voice.player import VoicePlayer

_BYTES_PER_SECOND = 22050 * 2 * 1  # 22050 Hz, 16-bit, mono


class RealTimeStream:
    """Fake output stream that consumes audio at (roughly) real time.

    ``write`` blocks until the "device" would have played the data, which is
    what makes a fast producer overflow the jitter buffer.
    """

    def __init__(self, bytes_per_second: int = _BYTES_PER_SECOND) -> None:
        self.bytes_per_second = bytes_per_second
        self.written = 0
        self.closed = False
        self._started = False
        self._t0 = 0.0
        self._lock = threading.Lock()
        self._pieces: list[bytes] = []

    def write(self, data: bytes) -> None:
        with self._lock:
            if not self._started:
                self._started = True
                self._t0 = time.monotonic()
            self.written += len(data)
            self._pieces.append(bytes(data))
            target = self._t0 + self.written / self.bytes_per_second
        delay = target - time.monotonic()
        if delay > 0:
            time.sleep(delay)

    def get_written_audio(self) -> bytes:
        with self._lock:
            return b"".join(self._pieces)

    def is_active(self) -> bool:
        return True

    def stop_stream(self) -> None:
        self.closed = True

    def close(self) -> None:
        self.closed = True


def _fast_chunks(total_bytes: int, chunk: int = 4096):
    """Yield PCM as fast as possible (a healthy, fast network stream)."""
    sent = 0
    while sent < total_bytes:
        n = min(chunk, total_bytes - sent)
        yield bytes([sent % 251]) * n
        sent += n


class TestNoAudioIsDropped(unittest.TestCase):
    def setUp(self) -> None:
        patcher = patch("voice.player.pyaudio")
        self.mock_pyaudio_mod = patcher.start()
        self.addCleanup(patcher.stop)
        self.mock_pyaudio_instance = MagicMock()
        self.mock_pyaudio_mod.PyAudio.return_value = self.mock_pyaudio_instance
        self.stream = RealTimeStream()
        self.mock_pyaudio_instance.open.return_value = self.stream
        self.player = VoicePlayer()

    def tearDown(self) -> None:
        self.player.shutdown()

    def _play_and_wait(self, chunks, timeout: float = 10.0) -> None:
        self.player.play_stream(chunks)
        deadline = time.monotonic() + timeout
        while self.player.is_playing and time.monotonic() < deadline:
            time.sleep(0.02)

    def test_fast_producer_loses_no_audio(self) -> None:
        """Every byte the source produced must reach the device.

        A fast source overflowing a small buffer must apply backpressure —
        never discard PCM.  Shrinking the buffer makes the overflow immediate.
        """
        total = _BYTES_PER_SECOND // 2  # 0.5 s of audio
        expected = b"".join(_fast_chunks(total))
        with patch("voice.player._JITTER_BUFFER_MS", 40), patch(
            "voice.player._MAX_JITTER_BUFFER_MS", 100
        ):
            self._play_and_wait(_fast_chunks(total))

        written = self.stream.get_written_audio()
        self.assertEqual(
            len(written), len(expected),
            f"dropped {len(expected) - len(written)} of {len(expected)} bytes",
        )
        # Order/continuity: the surviving audio must be the real signal, and
        # it must appear contiguously (no spliced discontinuities).
        self.assertIn(expected, written)

    def test_no_underruns_when_the_source_is_fast(self) -> None:
        """A source faster than real time must not starve the device."""
        total = _BYTES_PER_SECOND // 4  # 0.25 s
        with patch("voice.player._JITTER_BUFFER_MS", 40), patch(
            "voice.player._MAX_JITTER_BUFFER_MS", 100
        ):
            self._play_and_wait(_fast_chunks(total))
        self.assertEqual(self.player.last_underruns, 0)

    def test_received_bytes_are_accounted(self) -> None:
        """The player must expose how much the source delivered."""
        total = _BYTES_PER_SECOND // 4 + 1  # even: a whole number of frames
        # A bytes object cannot be produced faster than real time here, but
        # accounting must still be exact.
        with patch("voice.player._JITTER_BUFFER_MS", 20):
            self._play_and_wait(_fast_chunks(total))
        self.assertEqual(self.player.last_play_received, total)
        self.assertEqual(self.player.last_play_bytes, total)


class TestShortReplyStillPlays(unittest.TestCase):
    def setUp(self) -> None:
        patcher = patch("voice.player.pyaudio")
        self.mock_pyaudio_mod = patcher.start()
        self.addCleanup(patcher.stop)
        self.mock_pyaudio_instance = MagicMock()
        self.mock_pyaudio_mod.PyAudio.return_value = self.mock_pyaudio_instance
        self.stream = RealTimeStream()
        self.mock_pyaudio_instance.open.return_value = self.stream
        self.player = VoicePlayer()

    def tearDown(self) -> None:
        self.player.shutdown()

    def test_reply_shorter_than_the_buffer_plays_fully(self) -> None:
        """A sub-buffer reply must play every byte, not be discarded."""
        total = 4096  # far below the 400 ms fill target
        expected = b"".join(_fast_chunks(total))
        self.player.play_stream(_fast_chunks(total))
        deadline = time.monotonic() + 5.0
        while self.player.is_playing and time.monotonic() < deadline:
            time.sleep(0.02)
        self.assertEqual(len(self.stream.get_written_audio()), len(expected))


class _FrameCheckingStream(RealTimeStream):
    """Fake device that rejects partial sample frames exactly like PyAudio.

    PyAudio raises ``ValueError("not a whole number of frames")`` for a write
    whose length is not a whole number of sample frames; the player surfaced
    that as a write failure and aborted playback mid-utterance.
    """

    def __init__(self, frame_bytes: int = 2) -> None:
        super().__init__()
        self.frame_bytes = frame_bytes
        self.write_sizes: list[int] = []
        self.rejected: list[int] = []

    def write(self, data: bytes) -> None:
        self.write_sizes.append(len(data))
        if len(data) % self.frame_bytes != 0:
            self.rejected.append(len(data))
            raise ValueError("not a whole number of frames")
        super().write(data)


class TestWholeFrameWrites(unittest.TestCase):
    """Every write must cover whole sample frames."""

    def setUp(self) -> None:
        patcher = patch("voice.player.pyaudio")
        self.mock_pyaudio_mod = patcher.start()
        self.addCleanup(patcher.stop)
        self.mock_pyaudio_instance = MagicMock()
        self.mock_pyaudio_mod.PyAudio.return_value = self.mock_pyaudio_instance
        self.stream = _FrameCheckingStream()
        self.mock_pyaudio_instance.open.return_value = self.stream
        self.player = VoicePlayer()

    def tearDown(self) -> None:
        self.player.shutdown()

    def _play(self, chunks) -> None:
        self.player.play_stream(chunks)
        deadline = time.monotonic() + 10.0
        while self.player.is_playing and time.monotonic() < deadline:
            time.sleep(0.02)

    def test_odd_length_stream_never_writes_a_partial_frame(self) -> None:
        """An odd byte count must not abort playback mid-utterance."""
        total = 11025  # deliberately not a whole number of frames
        with patch("voice.player._JITTER_BUFFER_MS", 20):
            self._play(_fast_chunks(total))

        self.assertEqual(self.stream.rejected, [], "PyAudio would reject these")
        self.assertIsNone(self.player.last_play_error)
        # Every source byte reached the device, plus at most one pad sample.
        self.assertGreaterEqual(self.player.last_play_bytes, total)
        self.assertLessEqual(self.player.last_play_bytes, total + 1)

    def test_unaligned_chunk_boundaries_still_play_in_full(self) -> None:
        """Chunks whose sizes are not frame-aligned must not lose audio."""
        payload = bytes(range(256)) * 40  # 10240 bytes, even
        pieces = [payload[i:i + 333] for i in range(0, len(payload), 333)]
        with patch("voice.player._JITTER_BUFFER_MS", 20):
            self._play(iter(pieces))

        self.assertEqual(self.stream.rejected, [])
        self.assertIsNone(self.player.last_play_error)
        self.assertEqual(self.player.last_play_bytes, len(payload))
        # Byte-for-byte integrity: nothing dropped, reordered or duplicated.
        self.assertEqual(self.stream.get_written_audio(), payload)


class TestCancellationStillImmediate(unittest.TestCase):
    def setUp(self) -> None:
        patcher = patch("voice.player.pyaudio")
        self.mock_pyaudio_mod = patcher.start()
        self.addCleanup(patcher.stop)
        self.mock_pyaudio_instance = MagicMock()
        self.mock_pyaudio_mod.PyAudio.return_value = self.mock_pyaudio_instance
        self.stream = RealTimeStream()
        self.mock_pyaudio_instance.open.return_value = self.stream
        self.player = VoicePlayer()

    def tearDown(self) -> None:
        self.player.shutdown()

    def test_stop_returns_promptly_during_a_long_stream(self) -> None:
        """Barge-in must still stop playback quickly (no backpressure wedge)."""
        long_audio = _BYTES_PER_SECOND * 8  # 8 s if it were allowed to finish
        self.player.play_stream(_fast_chunks(long_audio))
        time.sleep(0.3)
        started = time.monotonic()
        self.player.stop()
        elapsed = time.monotonic() - started
        self.assertLess(elapsed, 3.0, f"stop() took {elapsed:.2f}s")
        self.assertFalse(self.player.is_playing)


if __name__ == "__main__":
    unittest.main()
