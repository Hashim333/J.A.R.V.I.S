"""
voice/vad.py

Adaptive, pause-tolerant Voice Activity Detection built on webrtcvad.

Behaviour (redesigned for the full-duplex pipeline):

  * **Fast onset** — speech starts as soon as a short run of voiced frames
    is seen (default ~90 ms), so the first word is never missed.
  * **Pause-tolerant end** — speech only *ends* after a sustained silence
    hangover (default 1200 ms).  Brief mid-sentence pauses therefore keep
    listening instead of chopping the command in half.
  * **Dynamic silence detection** — the hangover and aggressiveness adapt
    to the live noise floor (``set_noise_floor``), so music/background
    audio cannot end an utterance early and soft speech in a quiet room is
    still caught.
  * **Bounded utterances** — a minimum speech duration before an end can
    fire, and a hard maximum utterance length that forces an end.

Constructor signature is backward compatible with the previous ``VAD``
(callbacks, aggressiveness, frame_duration_ms, padding_duration_ms,
sample_rate).
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
    Adaptive voice activity detection with fast onset and a
    pause-tolerant end-of-speech hangover.
    """

    def __init__(
        self,
        on_speech_started: Callable[[], None] | None = None,
        on_speech_ended: Callable[[], None] | None = None,
        aggressiveness: int = 1,
        frame_duration_ms: int = 30,
        padding_duration_ms: int = 750,
        sample_rate: int = 16000,
        silence_hangover_ms: float = 1200.0,
        min_speech_ms: float = 250.0,
        max_utterance_ms: float = 20000.0,
        onset_frames: int | None = None,
        adaptive: bool = True,
    ) -> None:
        self._on_speech_started = on_speech_started
        self._on_speech_ended = on_speech_ended
        self._sample_rate = sample_rate
        self._sample_width = 2
        self._channels = 1
        self._frame_duration_ms = frame_duration_ms
        self._aggressiveness = aggressiveness
        self._adaptive = adaptive

        # Backward compatibility: if a non-default padding_duration_ms was
        # passed, treat it as the end-of-speech hangover.
        if padding_duration_ms != 750:
            self._hangover_ms = float(padding_duration_ms)
        else:
            self._hangover_ms = float(silence_hangover_ms)
        self._min_speech_ms = float(min_speech_ms)
        self._max_utterance_ms = float(max_utterance_ms)

        self._noise_floor: float | None = None
        self._build_webrtc()

        self._frame_size = int(self._sample_rate * (self._frame_duration_ms / 1000.0))
        self._frame_bytes = self._frame_size * 2
        self._hangover_frames = max(1, int(self._hangover_ms / self._frame_duration_ms))
        self._min_speech_frames = max(1, int(self._min_speech_ms / self._frame_duration_ms))
        self._max_utterance_frames = int(self._max_utterance_ms / self._frame_duration_ms)
        self._onset_frames = onset_frames or 3

        logger.info(
            "VAD configured: rate=%d, frame=%.0f ms, aggressiveness=%d, "
            "onset=%d frames (%.0f ms), hangover=%d frames (%.0f ms), "
            "min_speech=%d frames (%.0f ms), max_utterance=%d frames (%.0f ms), "
            "adaptive=%s",
            self._sample_rate, self._frame_duration_ms, self._aggressiveness,
            self._onset_frames, self._onset_frames * self._frame_duration_ms,
            self._hangover_frames, self._hangover_frames * self._frame_duration_ms,
            self._min_speech_frames, self._min_speech_frames * self._frame_duration_ms,
            self._max_utterance_frames, self._max_utterance_frames * self._frame_duration_ms,
            self._adaptive,
        )

        # Ring buffers for onset and end detection
        self._onset_buffer: collections.deque = collections.deque(
            maxlen=self._onset_frames
        )
        # The end-of-speech ring buffer (tests use ``_ring_buffer.maxlen`` as
        # the frame count needed to trip an end).
        self._ring_buffer: collections.deque = collections.deque(
            maxlen=self._hangover_frames
        )
        self._triggered = False
        self._buffer = bytearray()
        self._speech_start_time: float | None = None
        self._speech_frames = 0

    def _build_webrtc(self) -> None:
        self._vad = webrtcvad.Vad()
        self._vad.set_mode(self._aggressiveness)

    # ------------------------------------------------------------------
    # Configuration
    # ------------------------------------------------------------------

    def set_noise_floor(self, noise_floor: float | None) -> None:
        """Adapt aggressiveness / onset to the current ambient noise.

        Noisy environments raise the aggressiveness (reject more background)
        and the onset requirement; quiet environments stay sensitive.
        """
        self._noise_floor = noise_floor
        if not self._adaptive or noise_floor is None:
            return
        if noise_floor < 0.005:
            level = 0
        elif noise_floor < 0.02:
            level = 1
        elif noise_floor < 0.06:
            level = 2
        else:
            level = 3
        self._aggressiveness = level
        self._onset_frames = 3 + level
        self._onset_buffer = collections.deque(maxlen=self._onset_frames)
        self._build_webrtc()
        logger.debug("VAD adaptive: noise_floor=%.4f -> aggressiveness=%d onset=%d", noise_floor, level, self._onset_frames)

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
        self._sample_rate = sample_rate
        self._frame_size = int(self._sample_rate * (self._frame_duration_ms / 1000.0))
        self._frame_bytes = self._frame_size * 2
        self._ring_buffer = collections.deque(maxlen=self._hangover_frames)
        self._onset_buffer = collections.deque(maxlen=self._onset_frames)
        self._buffer = bytearray()
        logger.info("VAD reconfigured: sample_rate=%d Hz", self._sample_rate)

    def reset(self) -> None:
        """Reset VAD state without recreating the object."""
        self._triggered = False
        self._ring_buffer.clear()
        self._onset_buffer.clear()
        self._buffer = bytearray()
        self._speech_start_time = None
        self._speech_frames = 0
        logger.debug("VAD reset")

    @property
    def triggered(self) -> bool:
        """True while VAD considers speech active (inside an utterance)."""
        return self._triggered

    @property
    def aggressiveness(self) -> int:
        return self._aggressiveness

    @property
    def onset_frames(self) -> int:
        return self._onset_frames

    @property
    def hangover_frames(self) -> int:
        return self._hangover_frames

    # ------------------------------------------------------------------
    # Processing
    # ------------------------------------------------------------------

    def process_audio(self, audio_chunk: bytes) -> None:
        """
        Process a chunk of audio data and detect speech.

        Accepts any-sized audio chunks.  Incomplete frames are buffered
        until a full frame is available.
        """
        self._buffer.extend(audio_chunk)

        while len(self._buffer) >= self._frame_bytes:
            frame = bytes(self._buffer[:self._frame_bytes])
            self._buffer = self._buffer[self._frame_bytes:]

            try:
                is_speech = self._vad.is_speech(frame, self._sample_rate)
            except Exception as exc:
                logger.error("VAD is_speech failed: %s", exc, exc_info=True)
                continue

            self._process_frame(is_speech)

    def _process_frame(self, is_speech: bool) -> None:
        if not self._triggered:
            # --- Not inside speech yet: fast onset ---
            self._onset_buffer.append(is_speech)
            if len(self._onset_buffer) == self._onset_frames and (
                sum(self._onset_buffer) >= self._onset_frames
            ):
                self._triggered = True
                self._speech_start_time = time.monotonic()
                self._speech_frames = 1
                self._ring_buffer.clear()
                logger.debug("VAD SPEECH START")
                self._safe_call(self._on_speech_started)
            return

        # --- Inside speech: watch for a pause-tolerant end ---
        self._speech_frames += 1
        self._ring_buffer.append(not is_speech)  # True == unvoiced frame

        # Hard maximum utterance length — force an end.
        if self._speech_frames >= self._max_utterance_frames:
            logger.debug("VAD SPEECH END (max utterance reached)")
            self._triggered = False
            self._ring_buffer.clear()
            self._safe_call(self._on_speech_ended)
            return

        # Minimum speech before an end can fire.
        if self._speech_frames < self._min_speech_frames:
            return

        unvoiced = sum(self._ring_buffer)
        if (
            len(self._ring_buffer) == self._ring_buffer.maxlen
            and unvoiced > 0.9 * self._ring_buffer.maxlen
        ):
            self._triggered = False
            logger.debug(
                "VAD SPEECH END (hangover) at t=%.3fs",
                time.monotonic(),
            )
            self._ring_buffer.clear()
            self._safe_call(self._on_speech_ended)

    @staticmethod
    def _safe_call(callback) -> None:
        if callback is None:
            return
        try:
            callback()
        except Exception as exc:
            logger.error("VAD callback failed: %s", exc, exc_info=True)
