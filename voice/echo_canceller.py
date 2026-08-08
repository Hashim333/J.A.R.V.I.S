"""
voice/echo_canceller.py

Reference-based acoustic echo cancellation (NLMS adaptive filter).

The TTS player feeds back the exact PCM it writes to the speakers
(``set_reference``); the microphone stream is subtracted against that
reference (``process``).  Because JARVIS's own voice is the *only* signal
we have a reference for, cancelling it simultaneously:

  * removes JARVIS's voice from the captured mic (self-voice guard),
  * stops JARVIS's TTS from triggering barge-in / wake word,
  * removes the biggest source of phantom commands.

YouTube/Spotify/system audio has no reference channel here, so it is
handled by the downstream adaptive noise suppressor + dynamic VAD +
confidence-gated transcription instead.

Implementation notes:

  * Speaker->mic latency is *estimated* by cross-correlating the mic chunk
    against the reference history.  The filter is not allowed to adapt until
    a high-confidence delay is locked (a misaligned filter would diverge),
    and any large delay drift re-locks / re-seeds the filter.
  * The filter is block normalised least-mean-squares (NLMS) with a leak
    factor for long-term stability.
  * Double-talk protection freezes adaptation while the user is speaking
    loudly, so we never learn to cancel the user.
"""
from __future__ import annotations

import collections
import logging
import threading

logger = logging.getLogger(__name__)

try:
    import numpy as np
except Exception:  # pragma: no cover - numpy is a declared dependency
    np = None


def pcm16_to_float(data: bytes) -> list:
    """Decode 16-bit mono PCM bytes to normalized floats."""
    if np is None:
        raise RuntimeError("numpy is required for echo cancellation")
    arr = np.frombuffer(data, dtype=np.int16).astype(np.float64) / 32768.0
    return arr.tolist()


def float_to_pcm16(samples) -> bytes:
    """Encode float samples back to 16-bit mono PCM bytes."""
    if np is None:
        raise RuntimeError("numpy is required for echo cancellation")
    arr = np.asarray(samples, dtype=np.float64)
    arr = np.clip(arr, -1.0, 1.0) * 32767.0
    return arr.astype(np.int16).tobytes()


class EchoCanceller:
    """
    NLMS acoustic echo canceller keyed to a known playback reference.

    Args:
        sample_rate: Pipeline sample rate (Hz), typically 16000.
        filter_taps: Adaptive filter length (samples).  Larger covers longer
            room / device impulse responses at the cost of CPU.
        max_delay_ms: Maximum speaker->mic latency to search (ms).
        step_size: NLMS adaptation step.  Higher converges faster but is
            less stable under noise.
        lock_score: Minimum normalized-correlation score before the delay
            is trusted and adaptation begins.
        double_talk_ratio: When mic power exceeds reference power by this
            factor, assume the user is speaking and freeze adaptation.
    """

    def __init__(
        self,
        sample_rate: int = 16000,
        filter_taps: int = 320,
        max_delay_ms: float = 80.0,
        step_size: float = 0.1,
        lock_score: float = 0.6,
        double_talk_ratio: float = 4.0,
    ) -> None:
        self._sample_rate = sample_rate
        self._taps = max(32, int(filter_taps))
        self._max_delay = max(self._taps, int(sample_rate * max_delay_ms / 1000.0))
        self._step = step_size
        self._lock_score = lock_score
        self._double_talk_ratio = max(1.5, double_talk_ratio)
        self._eps = 1e-9

        self._delay = self._max_delay // 2
        self._delay_locked = False
        self._filter = np.zeros(self._taps, dtype=np.float64)
        self._leak = 0.99999
        # Reference history ring; large enough for max_delay + taps + a chunk.
        self._ref = collections.deque(maxlen=self._max_delay + self._taps + 2048)

        self._lock = threading.Lock()
        self._chunks_processed = 0
        self._estimate_every = 16
        self._erle = 0.0
        self._double_talk = False

    # ------------------------------------------------------------------
    # Reference feed (called from the TTS player thread)
    # ------------------------------------------------------------------

    def set_reference(self, pcm16_chunk: bytes) -> None:
        """Feed the exact PCM written to the speakers as the echo reference."""
        if np is None or not pcm16_chunk:
            return
        with self._lock:
            self._ref.extend(pcm16_to_float(pcm16_chunk))

    def reset(self) -> None:
        """Clear the filter and reference history (e.g. before a fresh capture)."""
        with self._lock:
            self._filter.fill(0.0)
            self._ref.clear()
            self._delay = self._max_delay // 2
            self._delay_locked = False
            self._erle = 0.0
            self._double_talk = False

    # ------------------------------------------------------------------
    # Processing
    # ------------------------------------------------------------------

    def process(self, mic_chunk: bytes) -> bytes:
        """Subtract the estimated echo from *mic_chunk* (pass-through until
        enough reference has been seen)."""
        if np is None:
            return mic_chunk
        with self._lock:
            return self._process_locked(mic_chunk)

    def _process_locked(self, mic_chunk: bytes) -> bytes:
        if not mic_chunk or len(mic_chunk) % 2 != 0:
            return mic_chunk

        mic = np.frombuffer(mic_chunk, dtype=np.int16).astype(np.float64) / 32768.0
        n = len(mic)
        need = self._max_delay + self._taps + n
        if len(self._ref) < need:
            return mic_chunk

        window = np.asarray(self._ref, dtype=np.float64)[-need:]

        # Delay estimation / locking.
        estimate = (not self._delay_locked) or (
            self._chunks_processed % self._estimate_every == 0
        )
        if estimate and not self._double_talk:
            self._estimate_delay(mic, window, n, need)
        if not self._delay_locked:
            self._chunks_processed += 1
            return mic_chunk  # no cancellation until delay is locked

        base = self._clamp_base(need - self._delay - n + 1, n)
        idx = (base + np.arange(n))[:, None] - np.arange(self._taps)[None, :]
        R = window[idx]  # (n, taps) reference feature matrix

        estimate_echo = R @ self._filter
        error = mic - estimate_echo

        mic_power = float(np.dot(mic, mic)) / max(n, 1)
        ref_power = float(np.dot(window, window)) / max(len(window), 1)
        double_talk = mic_power > self._double_talk_ratio * max(ref_power, 1e-12)
        self._double_talk = double_talk

        if not double_talk and ref_power > 1e-7:
            power = np.einsum("ij,ij->i", R, R)
            scale = self._step / (power + self._eps)
            update = (scale * error)[:, None] * R
            self._filter = self._filter * self._leak + update.sum(axis=0)

        error_power = float(np.dot(error, error)) / max(n, 1)
        if mic_power > 1e-9 and error_power > 1e-12:
            self._erle = 10.0 * np.log10(max(mic_power, 1e-12) / error_power)

        self._chunks_processed += 1
        out = np.clip(error, -1.0, 1.0) * 32767.0
        return out.astype(np.int16).tobytes()

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _clamp_base(self, base: int, n: int) -> int:
        lo = self._taps - 1
        hi = self._max_delay + self._taps
        return int(max(lo, min(hi, base)))

    def _estimate_delay(self, mic, window, n: int, need: int) -> None:
        """Cross-correlate the mic chunk against the reference to find the
        current speaker->mic lag (samples)."""
        mic_norm = float(np.dot(mic, mic)) + self._eps
        best_lag = self._delay
        best_score = -1.0
        for lag in range(0, self._max_delay + 1):
            start = need - lag - n
            if start < 0:
                break
            seg = window[start:start + n]
            denom = np.sqrt(float(np.dot(seg, seg)) * mic_norm) + self._eps
            score = float(np.dot(seg, mic)) / denom
            if score > best_score:
                best_score = score
                best_lag = lag

        if best_score < self._lock_score:
            return
        if not self._delay_locked or abs(best_lag - self._delay) > 32:
            # (Re)lock: reseed the filter because the alignment changed.
            self._delay_locked = True
            self._delay = best_lag
            self._filter.fill(0.0)
            logger.info(
                "EchoCanceller: delay %slocked at %d samples (%.1f ms), score=%.3f",
                "re" if self._delay_locked else "",
                best_lag, best_lag * 1000.0 / self._sample_rate, best_score,
            )
        else:
            # Small drift: track it without reseeding.
            self._delay = best_lag

    # ------------------------------------------------------------------
    # Diagnostics
    # ------------------------------------------------------------------

    @property
    def erle_db(self) -> float:
        """Echo Return Loss Enhancement estimate (dB, higher = better)."""
        return float(self._erle)

    @property
    def double_talk(self) -> bool:
        return self._double_talk

    @property
    def delay_samples(self) -> int:
        return self._delay

    @property
    def delay_locked(self) -> bool:
        return self._delay_locked

    @property
    def is_ready(self) -> bool:
        return len(self._ref) >= self._max_delay + self._taps + 64
