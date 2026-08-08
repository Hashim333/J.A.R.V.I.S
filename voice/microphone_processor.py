"""
voice/microphone_processor.py

Audio processing pipeline for microphone input: AGC, noise gate,
normalization, auto-calibration, and live audio level.
"""
import audioop
import logging
import time

logger = logging.getLogger(__name__)


class MicrophoneProcessor:
    """
    Processing pipeline for 16-bit mono PCM audio chunks.

    Stages (in order):
      1. RMS energy calculation (for level monitoring / logging)
      2. Auto-calibration — measure noise floor from first ~1 s of audio
      3. Sensitivity scaling (user-configurable multiplier)
      4. Automatic Gain Control — adaptively targets a configurable RMS level
      5. Noise gate — zeroes chunks still below threshold after AGC
      6. Peak normalization — prevents clipping after AGC overshoot

    Usage::

        processor = MicrophoneProcessor()
        processor.start()         # begins calibration period
        processed = processor.process_chunk(raw_chunk)
        level = processor.audio_level    # 0.0-1.0 for UI
        snr   = processor.signal_to_noise
        speech = processor.is_speech
    """

    def __init__(
        self,
        sample_rate: int = 16000,
        sample_width: int = 2,
        channels: int = 1,
        sensitivity: float = 1.0,
        agc_enabled: bool = True,
        agc_target_level: float = 0.15,
        agc_max_gain: float = 10.0,
        agc_attack: float = 0.3,
        agc_release: float = 0.02,
        noise_gate_enabled: bool = True,
        noise_gate_threshold: float = 0.02,
        calibration_duration: float = 1.0,
        normalization_target: float = 0.95,
    ):
        self._sample_rate = sample_rate
        self._sample_width = sample_width
        self._channels = channels

        self._sensitivity = sensitivity
        self._agc_enabled = agc_enabled
        self._agc_target_level = agc_target_level
        self._agc_max_gain = agc_max_gain
        self._agc_attack = agc_attack
        self._agc_release = agc_release
        self._noise_gate_enabled = noise_gate_enabled
        self._noise_gate_threshold = noise_gate_threshold
        self._calibration_duration = calibration_duration
        self._normalization_target = normalization_target

        self._running_rms: float = 0.0
        self._current_gain: float = 1.0
        self._noise_floor: float = 0.0
        self._calibration_samples: int = 0
        self._calibration_target: int = 0
        self._calibrated: bool = False
        self._calibration_buffer: list[float] = []
        self._started: bool = False

        self._audio_level: float = 0.0

    # ── Properties ────────────────────────────────────────────────────

    @property
    def audio_level(self) -> float:
        return self._audio_level

    @property
    def noise_floor(self) -> float:
        return self._noise_floor

    @property
    def signal_to_noise(self) -> float:
        if self._noise_floor <= 0:
            return 1.0
        return self._running_rms / self._noise_floor

    @property
    def is_speech(self) -> bool:
        return self._running_rms > self._noise_gate_threshold

    @property
    def current_gain(self) -> float:
        return self._current_gain

    @property
    def calibrated(self) -> bool:
        return self._calibrated

    @property
    def running_rms(self) -> float:
        return self._running_rms

    # ── Lifecycle ─────────────────────────────────────────────────────

    def start(self) -> None:
        """Begin calibration phase.  Idempotent."""
        if self._started:
            return
        self._started = True
        if self._calibration_duration > 0:
            chunk_duration = 1024 / self._sample_rate  # approximate per-chunk seconds
            self._calibration_target = max(
                1, int(self._calibration_duration / chunk_duration)
            )
            self._calibration_samples = 0
            self._calibration_buffer = []
            self._calibrated = False
            logger.info(
                "MicrophoneProcessor: calibration started "
                "(%d chunks, %.1f s)",
                self._calibration_target,
                self._calibration_duration,
            )
        else:
            self._calibrated = True

    def shutdown(self) -> None:
        """Reset all state."""
        self._started = False
        self._running_rms = 0.0
        self._current_gain = 1.0
        self._audio_level = 0.0
        self._calibrated = False
        self._calibration_buffer = []
        self._calibration_samples = 0

    def process_chunk(self, audio_chunk: bytes) -> bytes:
        """Run a 16-bit PCM chunk through the full processing pipeline."""
        if not audio_chunk or len(audio_chunk) < self._sample_width * self._channels:
            return audio_chunk

        chunk = audio_chunk

        # 1. RMS
        rms = self._calc_rms(chunk)
        self._running_rms = rms

        # 2. Auto-calibration (first N chunks)
        if not self._calibrated and self._calibration_target > 0:
            self._calibration_buffer.append(rms)
            self._calibration_samples += 1
            if self._calibration_samples >= self._calibration_target:
                self._finalize_calibration()
            return chunk

        # 3. Sensitivity scaling
        if self._sensitivity != 1.0:
            chunk = self._apply_gain(chunk, self._sensitivity)

        # 4. AGC — normalize level BEFORE the noise gate so quiet speech
        #    is boosted above the gate threshold instead of being zeroed.
        if self._agc_enabled and rms > 0:
            target_gain = self._agc_target_level / max(rms, 1e-10)
            target_gain = max(0.1, min(target_gain, self._agc_max_gain))
            if target_gain > self._current_gain:
                self._current_gain += (
                    (target_gain - self._current_gain) * self._agc_attack
                )
            else:
                self._current_gain += (
                    (target_gain - self._current_gain) * self._agc_release
                )
            chunk = self._apply_gain(chunk, self._current_gain)
            rms = self._calc_rms(chunk)
            self._running_rms = rms

        # 5. Noise gate — zeroes chunks still below threshold after AGC
        if self._noise_gate_enabled and rms <= self._noise_gate_threshold:
            logger.debug(
                "Noise gate: zeroing chunk (post-AGC rms=%.4f <= %.4f, gain=%.2f)",
                rms, self._noise_gate_threshold, self._current_gain,
            )
            self._audio_level = 0.0
            self._running_rms = 0.0
            return b'\x00' * len(chunk)

        # 6. Peak normalization
        if self._normalization_target < 1.0:
            peak = self._calc_peak(chunk)
            if peak > self._normalization_target:
                norm_gain = self._normalization_target / max(peak, 1e-10)
                chunk = self._apply_gain(chunk, norm_gain)

        # 7. Audio level for UI
        self._audio_level = min(1.0, rms * 5.0)

        return chunk

    # ── Internal helpers ──────────────────────────────────────────────

    def _calc_rms(self, chunk: bytes) -> float:
        try:
            return audioop.rms(chunk, self._sample_width) / 32768.0
        except Exception:
            return 0.0

    def _calc_peak(self, chunk: bytes) -> float:
        try:
            return audioop.max(chunk, self._sample_width) / 32768.0
        except Exception:
            return 0.0

    def _apply_gain(self, chunk: bytes, gain: float) -> bytes:
        if gain <= 0:
            return b'\x00' * len(chunk)
        if abs(gain - 1.0) < 0.01:
            return chunk
        try:
            return audioop.mul(chunk, self._sample_width, gain)
        except Exception:
            return chunk

    def _finalize_calibration(self) -> None:
        if not self._calibration_buffer:
            self._calibrated = True
            return
        sorted_vals = sorted(self._calibration_buffer)
        median_idx = len(sorted_vals) // 2
        self._noise_floor = sorted_vals[median_idx]
        self._calibrated = True
        logger.info(
            "MicrophoneProcessor: calibration complete — noise_floor=%.6f "
            "(from %d samples, %.1f s)",
            self._noise_floor,
            len(self._calibration_buffer),
            self._calibration_duration,
        )
        self._calibration_buffer = []
