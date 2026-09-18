"""
voice/silero_vad.py

Silero VAD — the capture / barge-in voice-activity detector for the
replaced speech pipeline.

Silero is far more robust than WebRTC VAD on noisy audio and is what the
pipeline spec calls for.  The state machine (fast onset, pause-tolerant
end-of-speech hangover, minimum speech duration, maximum utterance length,
noise-floor adaptation) matches ``voice.vad.VAD`` exactly, so the duplex
session and the tests can swap backends transparently:

  * the Silero model runs on ONNX with a single CPU thread (light enough
    for low-end PCs) and is loaded lazily so importing this module never
    pulls in torch,
  * if the Silero model cannot be loaded, detection **falls back to the
    existing WebRTC VAD** (``voice.vad.VAD``) so the pipeline never loses
    voice activity detection,
  * ``backend`` reports which engine is active (``"silero"`` /
    ``"webrtc"``).

The constructor is backward compatible with ``voice.vad.VAD``
(``on_speech_started`` / ``on_speech_ended`` / ``aggressiveness`` /
``frame_duration_ms`` / ``padding_duration_ms`` / ``sample_rate``).
"""
from __future__ import annotations

import collections
import logging
import threading
import time
from typing import Callable

from voice.vad import VAD

logger = logging.getLogger(__name__)

# Silero consumes exactly 512 samples (32 ms @ 16 kHz) per frame.
_SILERO_FRAME_SAMPLES = 512
_SILERO_FRAME_BYTES = _SILERO_FRAME_SAMPLES * 2

# VOICE-FIX: onset must reject noise blips without clipping soft speech.
# 0.55 start threshold + 5-frame majority onset below; end stays low so
# silence still ends the utterance promptly.
_START_THRESHOLD = 0.55
_END_THRESHOLD = 0.25


class SileroVAD:
    """
    Silero-based voice activity detection with fast onset and a
    pause-tolerant end-of-speech hangover (WebRTC fallback if unavailable).
    """

    def __init__(
        self,
        on_speech_started: Callable[[], None] | None = None,
        on_speech_ended: Callable[[], None] | None = None,
        aggressiveness: int = 1,
        frame_duration_ms: int = 30,
        padding_duration_ms: int = 750,
        sample_rate: int = 16000,
        silence_hangover_ms: float = 1500.0,
        min_speech_ms: float = 300.0,
        max_utterance_ms: float = 20000.0,
        onset_frames: int | None = None,
        adaptive: bool = True,
        model: object | None = None,
        onnx: bool = True,
        auto_load: bool = True,
    ) -> None:
        self._on_speech_started = on_speech_started
        self._on_speech_ended = on_speech_ended
        self._sample_rate = sample_rate
        self._frame_duration_ms = frame_duration_ms
        self._adaptive = adaptive
        self._start_threshold = _START_THRESHOLD
        self._end_threshold = _END_THRESHOLD

        if padding_duration_ms != 750:
            self._hangover_ms = float(padding_duration_ms)
        else:
            self._hangover_ms = float(silence_hangover_ms)
        self._min_speech_ms = float(min_speech_ms)
        self._max_utterance_ms = float(max_utterance_ms)

        self._noise_floor: float | None = None
        self._delegate: VAD | None = None
        self._silero = None
        self._pending_silero = None
        self._onnx = onnx
        self._load_thread: threading.Thread | None = None

        self._hangover_frames = max(1, int(self._hangover_ms / 32.0))
        self._min_speech_frames = max(1, int(self._min_speech_ms / 32.0))
        self._max_utterance_frames = int(self._max_utterance_ms / 32.0)
        self._onset_frames = onset_frames or 3

        # FIX-VOICE-003: track speech end time for latency logging
        self._speech_end_time: float | None = None

        self._reset_state()
        self._backend = self._try_load(model, auto_load=auto_load)

        logger.info(
            "SileroVAD configured: backend=%s rate=%d onset=%d frames "
            "hangover=%d frames (%d ms) min_speech=%d frames max_utterance=%d frames",
            self._backend, self._sample_rate, self._onset_frames,
            self._hangover_frames, int(self._hangover_frames * 32),
            self._min_speech_frames, self._max_utterance_frames,
        )

    def _try_load(self, model: object | None, auto_load: bool = True) -> str:
        """Activate the VAD backend.

        An injected model is used immediately.  Otherwise WebRTC VAD keeps
        detection working instantly and the Silero model is loaded on a
        background thread (importing torch + the model must never stall app
        startup or the microphone thread) — the detector upgrades to Silero
        the moment the model is ready.
        """
        if model is not None:
            self._silero = model
            return "silero"
        self._delegate = VAD(
            on_speech_started=self._on_speech_started,
            on_speech_ended=self._on_speech_ended,
            sample_rate=self._sample_rate,
            silence_hangover_ms=self._hangover_ms,
            min_speech_ms=self._min_speech_ms,
            max_utterance_ms=self._max_utterance_ms,
            onset_frames=self._onset_frames,
            adaptive=self._adaptive,
        )
        if auto_load:
            self._load_thread = threading.Thread(
                target=self._background_load,
                name="silero-vad-load",
                daemon=True,
            )
            self._load_thread.start()
        return "webrtc"

    def _background_load(self) -> None:
        """Load the Silero model and swap it in (never raises)."""
        try:
            from silero_vad import load_silero_vad

            silero = load_silero_vad(onnx=self._onnx)
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "Silero VAD unavailable (%s) — keeping WebRTC VAD", exc,
            )
            return
        # Do not replace WebRTC state in the middle of an utterance. Queue
        # the upgrade until the current delegate has returned to silence.
        if self._delegate is not None and self._delegate.triggered:
            self._pending_silero = silero
            logger.info("Silero VAD ready; deferring backend swap until speech ends")
            return
        self._activate_silero(silero)

    def _activate_silero(self, silero: object) -> None:
        self._silero = silero
        self._pending_silero = None
        self._delegate = None
        self._backend = "silero"
        self._reset_state()
        if self._noise_floor is not None:
            try:
                self.set_noise_floor(self._noise_floor)
            except Exception:
                pass
        logger.info("Silero VAD ready (switched from WebRTC fallback)")

    def _reset_state(self) -> None:
        self._onset_buffer: collections.deque = collections.deque(
            maxlen=self._onset_frames
        )
        self._ring_buffer: collections.deque = collections.deque(
            maxlen=self._hangover_frames
        )
        self._triggered = False
        self._buffer = bytearray()
        self._speech_start_time: float | None = None
        self._speech_frames = 0
        self._speech_end_time: float | None = None

    # ------------------------------------------------------------------
    # Configuration
    # ------------------------------------------------------------------

    def set_noise_floor(self, noise_floor: float | None) -> None:
        """Adapt sensitivity to the current ambient noise floor.

        Noisy environments raise the onset requirement and the speech
        probability threshold; quiet environments stay sensitive.

        NOISE-FLOOR-CAP: a high floor (music / TV) escalates only to a hard
        ceiling of 4 frames @ 0.6 probability.  Music is non-stationary so
        the tracked floor rides up with it, and speech-over-music rarely
        produces Silero probabilities >= 0.8 — an uncapped bar made every
        utterance time out as ``no_speech``.  Silero itself discriminates
        speech from music (instrumental audio scores well below 0.6);
        Whisper's confidence gate remains the false-positive safety net
        downstream.
        """
        self._noise_floor = noise_floor
        if self._delegate is not None:
            self._delegate.set_noise_floor(noise_floor)
            return
        if not self._adaptive or noise_floor is None:
            return
        if noise_floor < 0.005:
            self._onset_frames = 3
            self._start_threshold = _START_THRESHOLD
        elif noise_floor < 0.02:
            self._onset_frames = 4
            self._start_threshold = min(0.7, _START_THRESHOLD + 0.05)
        else:
            self._onset_frames = 4
            self._start_threshold = 0.6
        self._onset_buffer = collections.deque(maxlen=self._onset_frames)
        logger.debug(
            "SileroVAD adaptive: noise_floor=%.4f -> onset=%d start_threshold=%.2f",
            noise_floor, self._onset_frames, self._start_threshold,
        )

    def set_sample_rate(self, sample_rate: int) -> None:
        if sample_rate == self._sample_rate:
            return
        self._sample_rate = sample_rate
        if self._delegate is not None:
            self._delegate.set_sample_rate(sample_rate)
        else:
            logger.warning(
                "SileroVAD only supports 16 kHz; reconfigured to %d Hz",
                sample_rate,
            )
        self.reset()

    def reset(self) -> None:
        """Reset VAD state without recreating the object."""
        self._reset_state()
        if self._delegate is not None:
            self._delegate.reset()
        logger.debug("SileroVAD reset")

    # FIX-VOICE-003: expose speech end time for latency tracking
    @property
    def speech_end_time(self) -> float | None:
        return self._speech_end_time

    @property
    def triggered(self) -> bool:
        """True while VAD considers speech active (inside an utterance)."""
        if self._delegate is not None:
            return self._delegate.triggered
        return self._triggered

    @property
    def backend(self) -> str:
        return self._backend

    @property
    def aggressiveness(self) -> int:
        return 0 if self._delegate is None else self._delegate.aggressiveness

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
        """Process a 16-bit PCM chunk and detect speech."""
        if (
            self._pending_silero is not None
            and self._delegate is not None
            and not self._delegate.triggered
        ):
            self._activate_silero(self._pending_silero)
        if self._delegate is not None:
            self._delegate.process_audio(audio_chunk)
            return
        self._buffer.extend(audio_chunk)
        while len(self._buffer) >= _SILERO_FRAME_BYTES:
            frame = bytes(self._buffer[:_SILERO_FRAME_BYTES])
            del self._buffer[:_SILERO_FRAME_BYTES]
            try:
                prob = self._frame_probability(frame)
            except Exception as exc:
                logger.error("Silero VAD frame failed: %s", exc, exc_info=True)
                continue
            self._process_frame(prob >= self._start_threshold, prob)

    def _frame_probability(self, frame: bytes) -> float:
        import numpy as np
        import torch

        samples = (
            np.frombuffer(frame, dtype=np.int16).astype(np.float32) / 32768.0
        )
        tensor = torch.from_numpy(samples).unsqueeze(0)
        prob = self._silero(tensor, 16000)
        if hasattr(prob, "item"):
            prob = prob.item()
        return float(prob)

    @staticmethod
    def _onset_required(onset_frames: int) -> int:
        """Frames of the onset window that must be speech before triggering.

        (FIX-003) A strict "all frames must be speech" rule delays onset by a
        full window whenever a single low-probability frame lands inside it,
        which is what clips the first word.  A **majority** of the window
        (ceil of 2/3) makes onset immediate while still rejecting noise
        blips.
        """
        return max(1, (int(onset_frames) * 2 + 2) // 3)

    def _process_frame(self, is_speech: bool, prob: float) -> None:
        if not self._triggered:
            self._onset_buffer.append(is_speech)
            if sum(self._onset_buffer) >= self._onset_required(
                self._onset_frames
            ):
                self._triggered = True
                self._speech_start_time = time.monotonic()
                self._speech_frames = 1
                self._ring_buffer.clear()
                logger.debug("SileroVAD SPEECH START (prob=%.3f)", prob)
                self._safe_call(self._on_speech_started)
            return

        self._speech_frames += 1
        self._ring_buffer.append(prob < self._end_threshold)

        if self._speech_frames >= self._max_utterance_frames:
            self._speech_end_time = time.monotonic()
            logger.debug("SileroVAD SPEECH END (max utterance reached) at t=%.3fs", self._speech_end_time)
            self._triggered = False
            self._ring_buffer.clear()
            self._safe_call(self._on_speech_ended)
            return

        if self._speech_frames < self._min_speech_frames:
            return

        unvoiced = sum(self._ring_buffer)
        if (
            len(self._ring_buffer) == self._ring_buffer.maxlen
            and unvoiced > 0.9 * self._ring_buffer.maxlen
        ):
            self._triggered = False
            self._speech_end_time = time.monotonic()
            logger.debug(
                "SileroVAD SPEECH END (hangover) at t=%.3fs",
                self._speech_end_time,
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
            logger.error("SileroVAD callback failed: %s", exc, exc_info=True)
