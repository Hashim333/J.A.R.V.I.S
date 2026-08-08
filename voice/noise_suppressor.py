"""
voice/noise_suppressor.py

Adaptive spectral noise suppression.

Per-frame FFT suppression with a *minimum-tracking* per-bin noise floor:

  * while the user is silent, each bin's noise estimate decays down to the
    quietest observed energy and only creeps upward slowly,
  * speech bins (energy well above the tracked floor) receive near-unity
    gain, so the user's voice is preserved,
  * noise bins are attenuated by a configurable over-subtraction factor.

Because YouTube/Spotify/system audio has no reference channel for the echo
canceller, this adaptive suppressor (plus the dynamic VAD and confidence
gate) is what keeps that background audio from being transcribed as a
command: steady music is tracked as noise and suppressed, and the noise
floor feeds the dynamic silence thresholds.

Uses Weighted Overlap-Add with a sqrt-Hann window (perfect COLA at 50%
overlap), so the output is sample-accurate and length-preserving.
"""
from __future__ import annotations

import logging
import threading
from typing import Optional

logger = logging.getLogger(__name__)

try:
    import numpy as np
except Exception:  # pragma: no cover - numpy is a declared dependency
    np = None


def _pcm16_to_float(data: bytes):
    return np.frombuffer(data, dtype=np.int16).astype(np.float64) / 32768.0


def _float_to_pcm16(samples) -> bytes:
    arr = np.clip(np.asarray(samples, dtype=np.float64), -1.0, 1.0) * 32767.0
    return arr.astype(np.int16).tobytes()


class NoiseSuppressor:
    """
    Streaming adaptive spectral noise suppressor.

    Args:
        sample_rate: Pipeline sample rate (Hz).
        frame_size: FFT frame length (samples).  Must be a power of two.
        suppression_strength: Over-subtraction factor.  1.0 is gentle, 2.0+
            is aggressive.
        noise_floor_ratio: Minimum per-bin gain — prevents total removal
            and the "underwater" musical-noise artifacts.
        noise_smoothing: Rate at which the noise floor creeps upward
            (0..1, higher = slower/safer tracking).
        gain_smoothing: Cross-frame gain smoothing (0..1) to reduce
            musical noise.
    """

    def __init__(
        self,
        sample_rate: int = 16000,
        frame_size: int = 512,
        suppression_strength: float = 1.4,
        noise_floor_ratio: float = 0.15,
        noise_smoothing: float = 0.85,
        gain_smoothing: float = 0.5,
    ) -> None:
        self._sample_rate = sample_rate
        self._N = int(frame_size)
        self._hop = self._N // 2
        self._suppression = max(0.0, suppression_strength)
        self._floor = max(0.0, min(1.0, noise_floor_ratio))
        self._noise_smoothing = max(0.0, min(0.999, noise_smoothing))
        self._gain_smoothing = max(0.0, min(0.999, gain_smoothing))
        self._eps = 1e-9

        self._w = np.sqrt(np.hanning(self._N))
        # Constant-Overlap-Add normalization: for a sqrt-Hann window at 50%
        # overlap, the sum of squared windows equals 1.5 at every sample.
        self._cola = 1.5
        self._num_bins = self._N // 2 + 1

        self._noise_est = np.ones(self._num_bins) * 1e-3
        self._prev_gain = np.ones(self._num_bins)
        self._initialized = False
        # Streaming STFT state.  The pipeline is pre-padded by one hop so the
        # frame grid is globally aligned; buffers are trimmed in hop-aligned
        # chunks so alignment (and the OLA reconstruction) never drifts.
        self._latency = self._N - self._hop
        self._in_buf = np.zeros(self._hop, dtype=np.float64)
        self._in_start = 0
        self._out_buf = np.zeros(self._hop, dtype=np.float64)
        self._emitted = 0
        self._lock = threading.Lock()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def reset(self) -> None:
        """Reset noise floor and buffers (e.g. before a fresh capture)."""
        with self._lock:
            self._noise_est = np.ones(self._num_bins) * 1e-3
            self._prev_gain = np.ones(self._num_bins)
            self._initialized = False
            self._in_buf = np.zeros(0, dtype=np.float64)
            self._in_start = 0
            self._out_buf = np.zeros(0, dtype=np.float64)
            self._emitted = 0

    def process(self, chunk: bytes) -> bytes:
        """Suppress stationary noise in a 16-bit PCM chunk (length-preserving
        modulo the intrinsic STFT latency of ``frame_size - hop`` samples)."""
        if np is None:
            return chunk
        if not chunk or len(chunk) % 2 != 0:
            return chunk
        with self._lock:
            new = _pcm16_to_float(chunk)
            n_new = len(new)
            self._in_buf = np.concatenate([self._in_buf, new])
            total = len(self._in_buf)

            while self._in_start + self._N <= total:
                pos = self._in_start
                frame = self._in_buf[pos:pos + self._N] * self._w
                spectrum = np.fft.rfft(frame)
                mag = np.abs(spectrum)
                phase = np.angle(spectrum)
                self._track_noise(mag)
                frame_rms = float(np.sqrt(np.mean(frame * frame)))
                noise_rms = float(np.sqrt(np.mean(self._noise_est ** 2)))
                gain = self._compute_gain(mag, frame_rms, noise_rms)
                spectrum_out = (mag * gain) * np.exp(1j * phase)
                y = np.fft.irfft(spectrum_out, n=self._N) * self._w / self._cola
                need = pos + self._N
                if need > len(self._out_buf):
                    self._out_buf = np.concatenate(
                        [self._out_buf, np.zeros(need - len(self._out_buf))]
                    )
                self._out_buf[pos:need] += y
                self._in_start += self._hop

            emit_end = self._in_start - self._latency
            emit_start = self._emitted
            if emit_end > emit_start:
                emit_count = int(min(n_new, emit_end - emit_start))
                result = self._out_buf[emit_start:emit_start + emit_count]
                self._emitted += emit_count
                if self._emitted > 8192 and self._in_start > 8192:
                    # Compact BOTH buffers by the same settled amount so the
                    # global OLA coordinate frame stays aligned (out_buf position
                    # p always maps to in_buf position p).  Trimming in_buf by
                    # _in_start instead would misalign the frame grid and drop
                    # samples over time.
                    self._out_buf = self._out_buf[self._emitted:]
                    self._in_buf = self._in_buf[self._emitted:]
                    self._in_start -= self._emitted
                    self._emitted = 0
            else:
                result = np.zeros(0, dtype=np.float64)
            return _float_to_pcm16(result)

    @property
    def noise_floor(self) -> float:
        """Average tracked noise floor (0..1, RMS-like)."""
        if np is None or not self._initialized:
            return 0.0
        with self._lock:
            return float(np.mean(self._noise_est))

    @property
    def initialized(self) -> bool:
        return self._initialized

    # ------------------------------------------------------------------
    # DSP internals
    # ------------------------------------------------------------------

    def _track_noise(self, mag) -> None:
        """Minimum-tracking noise estimate: instant down, slow up."""
        if not self._initialized:
            self._noise_est = mag.copy()
            self._initialized = True
            return
        below = mag < self._noise_est
        self._noise_est[below] = mag[below]
        rising = ~below
        if np.any(rising):
            self._noise_est[rising] = (
                self._noise_smoothing * self._noise_est[rising]
                + (1.0 - self._noise_smoothing) * mag[rising]
            )

    def _compute_gain(self, mag, frame_rms: float, noise_rms: float):
        ratio = self._noise_est / (mag + self._eps)
        gain = np.clip(1.0 - self._suppression * ratio, self._floor, 1.0)
        # Speech-presence gate: strong frames are speech — respond
        # immediately instead of lagging through the gain smoother, so the
        # first syllables are never attenuated.
        speech_present = frame_rms > 3.0 * max(noise_rms, 1e-6)
        if speech_present:
            self._prev_gain = gain
        elif self._gain_smoothing > 0.0:
            gain = (
                self._gain_smoothing * self._prev_gain
                + (1.0 - self._gain_smoothing) * gain
            )
            self._prev_gain = gain
        return gain
