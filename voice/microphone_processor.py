"""
voice/microphone_processor.py

Audio processing pipeline for microphone input: DC-offset removal,
high-pass filtering, AGC, adaptive noise gate, speech normalization,
auto-calibration, and live audio level.

(FIX-003) Two new front-end stages were added ahead of the existing AGC /
noise-gate chain:

  * **DC-offset removal** — a leaky-running-mean estimator is subtracted
    from every sample so mic bias / drift never inflates the RMS that the
    AGC and the noise gate measure (DC looks like low-frequency rumble to
    a voice detector).
  * **High-pass filter** — a 2nd-order Butterworth (default ~80 Hz) kills
    rumble, breath pops and mains hum before the AGC measures the level;
    the pass band is unity-gain so genuine speech is untouched.
  * **Adaptive noise gate** — when calibration has measured a real noise
    floor, the gate threshold rises to ``max(configured, floor * margin)``
    so a noisy room is gated correctly while a quiet room stays at the
    configured threshold.
  * **Speech normalization** — a gentle final leveler that lifts quiet-but-
    valid speech (between the gate floor and a boost ceiling) toward a
    target RMS, so it clears the noise gate without the AGC having to run
    at maximum gain.

Stages (in order):
  1. DC-offset removal (running-mean subtract)
  2. High-pass filter (Butterworth, ~80 Hz)
  3. RMS energy calculation (for level monitoring / logging)
  4. Auto-calibration — measure noise floor from first ~1 s of audio
  5. Sensitivity scaling (user-configurable multiplier)
  6. Automatic Gain Control — adaptively targets a configurable RMS level
  7. Speech normalization — lift quiet-but-valid speech toward a target RMS
  8. Adaptive noise gate — zeroes chunks still below threshold after AGC
  9. Peak normalization — prevents clipping after AGC overshoot

Usage::

    processor = MicrophoneProcessor()
    processor.start()         # begins calibration period
    processed = processor.process_chunk(raw_chunk)
    level = processor.audio_level    # 0.0-1.0 for UI
    snr   = processor.signal_to_noise
    speech = processor.is_speech
"""
import audioop
import logging
import math
import struct
import time

logger = logging.getLogger(__name__)

# GATE-CEILING: the adaptive gate may never exceed this RMS.  Calibration is
# one-shot at startup, so a floor measured while music was playing would
# otherwise set gate = floor * margin above post-AGC speech (~0.15 target)
# and zero chunks mid-word.  0.10 still gates fans/hum in quiet rooms
# (floor <= ~0.066) while guaranteeing headroom for normal speech.
_GATE_CEILING = 0.10


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
        dc_removal_enabled: bool = True,
        high_pass_enabled: bool = True,
        high_pass_cutoff_hz: float = 80.0,
        speech_normalization_enabled: bool = True,
        speech_target_rms: float = 0.15,
        speech_boost_ceiling: float = 0.08,
        noise_floor_margin: float = 1.5,
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

        self._dc_removal_enabled = bool(dc_removal_enabled)
        self._high_pass_enabled = bool(high_pass_enabled)
        self._high_pass_cutoff_hz = float(high_pass_cutoff_hz)
        self._speech_normalization_enabled = bool(speech_normalization_enabled)
        self._speech_target_rms = float(speech_target_rms)
        self._speech_boost_ceiling = float(speech_boost_ceiling)
        self._noise_floor_margin = float(noise_floor_margin)

        self._dc_alpha = 0.002
        self._dc_estimate: float = 0.0
        self._hp_b0 = 0.0
        self._hp_b1 = 0.0
        self._hp_b2 = 0.0
        self._hp_a1 = 0.0
        self._hp_a2 = 0.0
        self._hp_x1 = 0.0
        self._hp_x2 = 0.0
        self._hp_y1 = 0.0
        self._hp_y2 = 0.0
        self._init_high_pass_coefficients()

        self._running_rms: float = 0.0
        self._current_gain: float = 1.0
        self._noise_floor: float = 0.0
        self._calibration_samples: int = 0
        self._calibration_target: int = 0
        self._calibrated: bool = False
        self._calibration_buffer: list[float] = []
        self._started: bool = False

        self._audio_level: float = 0.0

    def _init_high_pass_coefficients(self) -> None:
        """Design a 2nd-order Butterworth high-pass at ``_high_pass_cutoff_hz``.

        The pass band is unity gain so speech above the cutoff is untouched;
        only DC / low-frequency rumble is removed.
        """
        if self._sample_rate <= 0:
            return
        k = math.tan(math.pi * self._high_pass_cutoff_hz / self._sample_rate)
        k2 = k * k
        den = 1.0 + math.sqrt(2.0) * k + k2
        self._hp_b0 = 1.0 / den
        self._hp_b1 = -2.0 * self._hp_b0
        self._hp_b2 = self._hp_b0
        self._hp_a1 = 2.0 * (k2 - 1.0) / den
        self._hp_a2 = (1.0 - math.sqrt(2.0) * k + k2) / den

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
        self._dc_estimate = 0.0
        self._hp_x1 = self._hp_x2 = self._hp_y1 = self._hp_y2 = 0.0

    def process_chunk(self, audio_chunk: bytes) -> bytes:
        """Run a 16-bit PCM chunk through the full processing pipeline."""
        if not audio_chunk or len(audio_chunk) < self._sample_width * self._channels:
            return audio_chunk

        chunk = audio_chunk

        # 1. DC-offset removal + high-pass filter (clean the signal BEFORE
        #    any level measurement so AGC / gate / calibration see clean audio).
        if self._dc_removal_enabled or self._high_pass_enabled:
            chunk = self._remove_dc_and_high_pass(chunk)

        # 2. RMS
        rms = self._calc_rms(chunk)
        self._running_rms = rms

        # 3. Auto-calibration (first N chunks)
        if not self._calibrated and self._calibration_target > 0:
            self._calibration_buffer.append(rms)
            self._calibration_samples += 1
            if self._calibration_samples >= self._calibration_target:
                self._finalize_calibration()
            return chunk

        # 4. Sensitivity scaling
        if self._sensitivity != 1.0:
            chunk = self._apply_gain(chunk, self._sensitivity)

        # 5. AGC — normalize level BEFORE the noise gate so quiet speech
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

        # 6. Speech normalization — lift quiet-but-valid speech (above the
        #    gate floor, below the boost ceiling) toward the target RMS so
        #    soft commands clear the noise gate without the AGC maxing out.
        gate = self._effective_gate_threshold()
        if (
            self._speech_normalization_enabled
            and gate < rms < self._speech_boost_ceiling
        ):
            target_gain = self._speech_target_rms / max(rms, 1e-10)
            target_gain = max(1.0, min(target_gain, self._agc_max_gain))
            if target_gain > 1.0:
                chunk = self._apply_gain(chunk, target_gain)
                rms = self._calc_rms(chunk)
                self._running_rms = rms

        # 7. Noise gate — VOICE-FIX soft gate: chunks clearly below the
        # threshold are zeroed, but chunks just under it (soft onsets /
        # quiet consonants, rms > gate*0.5) are attenuated, not destroyed.
        # Hard-zeroing onsets starves Whisper of the first phoneme and
        # collapses confidence / causes hallucinations.
        if self._noise_gate_enabled and rms <= gate:
            if rms > gate * 0.5:
                chunk = self._apply_gain(chunk, 0.25)
                rms = self._calc_rms(chunk)
                self._running_rms = rms
                self._audio_level = min(1.0, rms * 5.0)
                return chunk
            logger.debug(
                "Noise gate: zeroing chunk (post-AGC rms=%.4f <= %.4f, gain=%.2f)",
                rms, gate, self._current_gain,
            )
            self._audio_level = 0.0
            self._running_rms = 0.0
            return b'\x00' * len(chunk)

        # 8. Peak normalization
        if self._normalization_target < 1.0:
            peak = self._calc_peak(chunk)
            if peak > self._normalization_target:
                norm_gain = self._normalization_target / max(peak, 1e-10)
                chunk = self._apply_gain(chunk, norm_gain)

        # 9. Audio level for UI
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

    def _effective_gate_threshold(self) -> float:
        """The noise-gate threshold, raised above ambient noise once
        calibration has measured a real noise floor.

        A quiet room (noise_floor ~ 0) keeps the configured threshold; a
        noisy room gates at ``noise_floor * margin`` so steady background
        cannot slip through the AGC boost.  The result is clamped to
        ``_GATE_CEILING`` so a music-contaminated calibration can never gate
        away normal speech.
        """
        if self._noise_floor > 0:
            return min(
                _GATE_CEILING,
                max(
                    self._noise_gate_threshold,
                    self._noise_floor * self._noise_floor_margin,
                ),
            )
        return self._noise_gate_threshold

    def _remove_dc_and_high_pass(self, chunk: bytes) -> bytes:
        """Remove DC offset and high-pass filter a 16-bit PCM chunk.

        Both stages are single-pass over the chunk and carry state across
        chunks (leaky DC estimator + biquad high-pass).  The output is the
        same length and is clipped to int16 range.
        """
        if len(chunk) % 2 != 0:
            return chunk
        try:
            samples = struct.unpack("<%dh" % (len(chunk) // 2), chunk)
        except (struct.error, ValueError):
            return chunk

        dc_on = self._dc_removal_enabled
        hp_on = self._high_pass_enabled
        dc = self._dc_estimate
        x1, x2 = self._hp_x1, self._hp_x2
        y1, y2 = self._hp_y1, self._hp_y2
        b0, b1, b2 = self._hp_b0, self._hp_b1, self._hp_b2
        a1, a2 = self._hp_a1, self._hp_a2
        alpha = self._dc_alpha

        out = []
        append = out.append
        for x in samples:
            if dc_on:
                dc += alpha * (x - dc)
                x = x - dc
            if hp_on:
                y = b0 * x + b1 * x1 + b2 * x2 - a1 * y1 - a2 * y2
                x2, x1 = x1, x
                y2, y1 = y1, y
            else:
                y = x
            if y >= 32767.0:
                append(32767)
            elif y <= -32768.0:
                append(-32768)
            else:
                append(int(round(y)))

        self._dc_estimate = dc
        self._hp_x1, self._hp_x2 = x1, x2
        self._hp_y1, self._hp_y2 = y1, y2
        return struct.pack("<%dh" % len(samples), *out)

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
        # P0: use the 25th percentile, not the median.  The conversation
        # loop starts listening immediately, so the first second can contain
        # user speech (observed: SPEECH DETECTED before calibration
        # complete); a median then locks the noise floor to speech RMS and
        # desensitizes the gate + VAD adaptation for the whole session.
        # The quiet quartile is ambient unless >75% of the window is loud,
        # in which case it degrades to the old median-like behavior.
        p25_idx = max(0, min(len(sorted_vals) - 1, len(sorted_vals) // 4))
        self._noise_floor = sorted_vals[p25_idx]
        self._calibrated = True
        logger.info(
            "MicrophoneProcessor: calibration complete — noise_floor=%.6f "
            "(from %d samples, %.1f s)",
            self._noise_floor,
            len(self._calibration_buffer),
            self._calibration_duration,
        )
        self._calibration_buffer = []
