"""
voice/vad.py

Voice Activity Detection (VAD) using the webrtcvad library.
"""
from __future__ import annotations

import collections
import logging
import time
from typing import Callable

import webrtcvad

logger = logging.getLogger(__name__)


class VAD:
    """
    Voice Activity Detection (VAD) that processes audio chunks and triggers
    callbacks for speech start and end.
    """

    def __init__(
        self,
        on_speech_started: Callable[[], None] | None = None,
        on_speech_ended: Callable[[], None] | None = None,
        aggressiveness: int = 1,
        frame_duration_ms: int = 30,
        padding_duration_ms: int = 300,
        sample_rate: int = 16000,
    ) -> None:
        self._on_speech_started = on_speech_started
        self._on_speech_ended = on_speech_ended
        self._sample_rate = sample_rate
        self._sample_width = 2
        self._channels = 1
        self._frame_duration_ms = frame_duration_ms
        self._padding_duration_ms = padding_duration_ms
        self._aggressiveness = aggressiveness

        # Initialize VAD
        self._vad = webrtcvad.Vad()
        self._vad.set_mode(aggressiveness)

        # Calculate frame size and padding frames
        self._frame_size = int(
            self._sample_rate * (self._frame_duration_ms / 1000.0)
        )
        self._frame_bytes = self._frame_size * 2
        num_padding_frames = int(self._padding_duration_ms / self._frame_duration_ms)

        logger.info(
            "VAD configured: sample_rate=%d Hz, channels=%d, sample_width=%d bytes, "
            "bytes_per_second=%d, frame_size=%d samples (%d bytes / %.0f ms), "
            "padding=%d frames (%.0f ms), aggressiveness=%d",
            self._sample_rate, self._channels, self._sample_width,
            self._sample_rate * self._sample_width * self._channels,
            self._frame_size, self._frame_bytes,
            self._frame_duration_ms,
            num_padding_frames, self._padding_duration_ms,
            aggressiveness,
        )

        # Ring buffer to hold audio frames
        self._ring_buffer = collections.deque(
            maxlen=num_padding_frames
        )
        self._triggered = False
        # Buffer for incomplete audio frames (any chunk size accepted)
        self._buffer = bytearray()
        self._speech_start_time: float | None = None

    def set_sample_rate(self, sample_rate: int) -> None:
        supported_rates = (8000, 16000, 32000, 48000)
        if sample_rate not in supported_rates:
            logger.error(
                "VAD sample rate %d Hz is unsupported; WebRTC VAD supports %s Hz",
                sample_rate,
                supported_rates,
            )
            return
        if sample_rate == self._sample_rate:
            return
        logger.info(
            "VAD sample rate changed: %d Hz -> %d Hz",
            self._sample_rate, sample_rate,
        )
        self._sample_rate = sample_rate
        self._frame_size = int(
            self._sample_rate * (self._frame_duration_ms / 1000.0)
        )
        self._frame_bytes = self._frame_size * 2
        num_padding_frames = int(self._padding_duration_ms / self._frame_duration_ms)
        self._ring_buffer = collections.deque(maxlen=num_padding_frames)
        self._buffer = bytearray()
        logger.info(
            "VAD reconfigured: sample_rate=%d Hz, channels=%d, "
            "sample_width=%d bytes, bytes_per_second=%d, frame_size=%d samples "
            "(%d bytes / %.0f ms), padding=%d frames",
            self._sample_rate,
            self._channels,
            self._sample_width,
            self._sample_rate * self._sample_width * self._channels,
            self._frame_size,
            self._frame_bytes,
            self._frame_duration_ms,
            num_padding_frames,
        )

    def reset(self) -> None:
        """Reset VAD state without recreating the object."""
        self._triggered = False
        self._ring_buffer.clear()
        self._buffer = bytearray()
        logger.debug("VAD reset")

    def process_audio(self, audio_chunk: bytes) -> None:
        """
        Process a chunk of audio data and detect speech.

        Accepts any-sized audio chunks. Incomplete frames are
        buffered internally until a full frame is available.
        """
        self._buffer.extend(audio_chunk)
        logger.debug(
            "VAD received chunk: bytes=%d, sample_rate=%d Hz, channels=%d, "
            "sample_width=%d bytes, expected_duration=%.1f ms",
            len(audio_chunk),
            self._sample_rate,
            self._channels,
            self._sample_width,
            len(audio_chunk)
            / (self._sample_rate * self._sample_width * self._channels)
            * 1000,
        )

        while len(self._buffer) >= self._frame_bytes:
            frame = bytes(self._buffer[:self._frame_bytes])
            self._buffer = self._buffer[self._frame_bytes:]

            try:
                is_speech = self._vad.is_speech(frame, self._sample_rate)
            except Exception as exc:
                logger.error("VAD is_speech failed: %s", exc, exc_info=True)
                continue

            if not self._triggered:
                self._ring_buffer.append((frame, is_speech))
                num_voiced = len([f for f, s in self._ring_buffer if s])
                if num_voiced > 0.9 * self._ring_buffer.maxlen:
                    self._triggered = True
                    self._speech_start_time = time.monotonic()
                    logger.info(
                        "VAD SPEECH START at t=%.3fs (padding=%d ms, "
                        "frame_duration=%d ms, aggressiveness=%d)",
                        self._speech_start_time,
                        self._padding_duration_ms,
                        self._frame_duration_ms,
                        self._aggressiveness,
                    )
                    try:
                        if self._on_speech_started:
                            self._on_speech_started()
                    except Exception as exc:
                        logger.error("on_speech_started callback failed: %s", exc, exc_info=True)
                    self._ring_buffer.clear()
            else:
                self._ring_buffer.append((frame, is_speech))
                num_unvoiced = len([f for f, s in self._ring_buffer if not s])
                if num_unvoiced > 0.9 * self._ring_buffer.maxlen:
                    self._triggered = False
                    speech_end_time = time.monotonic()
                    capture_duration_ms = (
                        (speech_end_time - self._speech_start_time) * 1000
                        if self._speech_start_time else 0.0
                    )
                    logger.info(
                        "VAD SPEECH END at t=%.3fs (capture_duration=%.0f ms, "
                        "padding=%d ms, frame_duration=%d ms)",
                        speech_end_time,
                        capture_duration_ms,
                        self._padding_duration_ms,
                        self._frame_duration_ms,
                    )
                    try:
                        if self._on_speech_ended:
                            self._on_speech_ended()
                    except Exception as exc:
                        logger.error("on_speech_ended callback failed: %s", exc, exc_info=True)
                    self._ring_buffer.clear()

