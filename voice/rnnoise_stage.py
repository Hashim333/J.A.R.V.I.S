"""
voice/rnnoise_stage.py

RNNoise stage — the dedicated noise-reduction block that sits **before**
STT in the replaced speech pipeline:

    raw mic -> echo canceller -> RNNoise stage -> { wake, VAD + Whisper STT,
                                                    barge-in }

RNNoise is a recurrent noise-suppression model; when the native ``rnnoise``
bindings are importable they are used (48 kHz, 480-sample frames).  There is
no pip wheel for ``rnnoise`` on this platform, so the stage transparently
falls back to the adaptive FFT suppressor (``voice.noise_suppressor``) which
already tracks the per-bin noise floor and feeds the dynamic VAD thresholds.
Both engines share one interface, so the duplex session and the tests never
care which one is active.
"""
from __future__ import annotations

import logging
from typing import Any

from voice.noise_suppressor import NoiseSuppressor

logger = logging.getLogger(__name__)

_NATIVE_SAMPLE_RATE = 48000
_NATIVE_FRAME = 480  # 10 ms @ 48 kHz
_NATIVE_FRAME_BYTES = _NATIVE_FRAME * 2


class _NativeRNNoise:
    """Native rnnoise wrapper (48 kHz, 480-sample frames).

    The pipeline runs at 16 kHz, so audio is linearly resampled up to 48 kHz
    for the model and back down to 16 kHz afterwards.  Only used when the
    native module imports successfully.
    """

    def __init__(self) -> None:
        import rnnoise  # noqa: F401  (import guard lives in the factory)

        self._denoiser = rnnoise.DenoiseState()
        self._up = bytearray()
        self._down = bytearray()
        self._leftover: list[float] = []
        self._emitted = bytearray()

    def process(self, chunk: bytes) -> bytes:
        self._up.extend(chunk)
        # Upsample 16k -> 48k (3x linear).
        processed = bytearray()
        out = list(self._leftover)
        n = len(self._up) // 2
        if n >= 2:
            samples = _as_float(self._up[: (n // 2) * 2])
            self._up = self._up[(n // 2) * 2:]
            for i in range(len(samples) - 1):
                out.extend([samples[i], (samples[i] + samples[i + 1]) / 2.0, samples[i + 1]])
            self._leftover = [samples[-1]]
            for k in range(0, len(out) - _NATIVE_FRAME + 1, _NATIVE_FRAME):
                frame = out[k:k + _NATIVE_FRAME]
                filtered = self._denoiser.process_frame(frame)
                processed.extend(_as_bytes(filtered))
            self._leftover = out[len(out) - len(out) % _NATIVE_FRAME:] if len(out) % _NATIVE_FRAME else self._leftover
            self._leftover = out[len(out) - (len(out) % _NATIVE_FRAME or _NATIVE_FRAME):] if len(out) % _NATIVE_FRAME else []
        # Downsample 48k -> 16k (decimate by 3).
        self._down.extend(processed)
        kept = bytearray()
        m = len(self._down) // 2
        if m >= 3:
            src = _as_float(self._down[: (m // 3) * 3 * 2])
            self._down = self._down[(m // 3) * 3 * 2:]
            kept.extend(_as_bytes(src[::3]))
        return bytes(kept)

    def reset(self) -> None:
        self._up = bytearray()
        self._down = bytearray()
        self._leftover = []
        self._emitted = bytearray()


def _as_float(data: bytes) -> list[float]:
    import array

    return [s / 32768.0 for s in array.array("h", data)]


def _as_bytes(samples: list[float]) -> bytes:
    import array

    return array.array(
        "h", (max(-32767, min(32767, int(round(s * 32767.0)))) for s in samples)
    ).tobytes()


def _try_native(sample_rate: int) -> _NativeRNNoise | None:
    if sample_rate != 16000:
        logger.debug("RNNoise stage: native path requires 16 kHz pipeline")
        return None
    try:
        import rnnoise  # noqa: F401

        return _NativeRNNoise()
    except Exception as exc:  # noqa: BLE001
        logger.info("RNNoise stage: native rnnoise unavailable (%s) — using FFT suppressor", exc)
        return None


class RNNoiseStage:
    """
    Noise-reduction stage placed before STT.

    Uses native RNNoise when importable, otherwise the adaptive FFT
    suppressor.  Exposes ``process`` / ``reset`` / ``noise_floor`` /
    ``initialized`` so the duplex session treats it like the suppressor it
    replaces.
    """

    def __init__(
        self,
        sample_rate: int = 16000,
        fallback: Any | None = None,
    ) -> None:
        self._sample_rate = sample_rate
        self._native = _try_native(sample_rate)
        if self._native is None:
            self._fallback = fallback or NoiseSuppressor(sample_rate=sample_rate)
        else:
            self._fallback = None

    @property
    def backend(self) -> str:
        return "rnnoise" if self._native is not None else "fft"

    def process(self, chunk: bytes) -> bytes:
        if self._native is not None:
            try:
                return self._native.process(chunk)
            except Exception as exc:
                logger.error("Native RNNoise failed — falling back for chunk: %s", exc, exc_info=True)
                return chunk
        return self._fallback.process(chunk)

    def reset(self) -> None:
        if self._native is not None:
            try:
                self._native.reset()
            except Exception:
                pass
        elif self._fallback is not None:
            self._fallback.reset()

    @property
    def noise_floor(self) -> float:
        if self._native is not None:
            return 0.0
        try:
            return float(self._fallback.noise_floor)
        except Exception:
            return 0.0

    @property
    def initialized(self) -> bool:
        if self._native is not None:
            return True
        return bool(getattr(self._fallback, "initialized", False))
