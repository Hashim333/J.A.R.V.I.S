"""
tests/test_rnnoise_stage.py

Unit tests for voice/rnnoise_stage.py.

The native ``rnnoise`` module is not pip-installable on this platform, so the
tests focus on the FFT fallback path plus the native wrapper logic that runs
regardless (resampling math).  A fake ``rnnoise`` module can be injected to
exercise the native branch.
"""

from __future__ import annotations

import unittest
from unittest.mock import patch

import numpy as np

from voice.rnnoise_stage import (
    RNNoiseStage,
    _NativeRNNoise,
    _as_bytes,
    _as_float,
)


class _FakeDenoise:
    def __init__(self) -> None:
        self.frames = 0

    def process_frame(self, frame) -> list[float]:
        self.frames += 1
        return list(frame)


class _FakeRNNoiseModule:
    """Stand-in for the native rnnoise module."""

    def __init__(self) -> None:
        self.DenoiseState = _FakeDenoise


class _FakeFallback:
    def __init__(self) -> None:
        self.processed = 0
        self.reset_count = 0
        self.noise_floor = 0.01
        self.initialized = True

    def process(self, chunk: bytes) -> bytes:
        self.processed += 1
        return chunk

    def reset(self) -> None:
        self.reset_count += 1


def _silence(n_frames: int) -> bytes:
    return (b"\x00\x00" * 16000) * n_frames


class TestRNNoiseFallback(unittest.TestCase):
    def test_backend_is_fft_without_native(self) -> None:
        stage = RNNoiseStage(sample_rate=16000, fallback=_FakeFallback())
        self.assertEqual(stage.backend, "fft")

    def test_fallback_used_when_native_missing(self) -> None:
        fallback = _FakeFallback()
        stage = RNNoiseStage(sample_rate=16000, fallback=fallback)
        out = stage.process(b"\x00\x00" * 3200)
        self.assertEqual(fallback.processed, 1)
        self.assertEqual(out, b"\x00\x00" * 3200)

    def test_process_zero_length_is_ok(self) -> None:
        fallback = _FakeFallback()
        stage = RNNoiseStage(sample_rate=16000, fallback=fallback)
        self.assertEqual(stage.process(b""), b"")
        self.assertEqual(fallback.processed, 1)

    def test_noise_floor_and_initialized_delegate(self) -> None:
        fallback = _FakeFallback()
        stage = RNNoiseStage(sample_rate=16000, fallback=fallback)
        self.assertEqual(stage.noise_floor, 0.01)
        self.assertTrue(stage.initialized)

    def test_reset_delegates_to_fallback(self) -> None:
        fallback = _FakeFallback()
        stage = RNNoiseStage(sample_rate=16000, fallback=fallback)
        stage.reset()
        self.assertEqual(fallback.reset_count, 1)


class TestRNNoiseNative(unittest.TestCase):
    def test_native_backend_when_module_importable(self) -> None:
        fake = _FakeRNNoiseModule()
        with patch("voice.rnnoise_stage._try_native") as try_native:
            try_native.return_value = None
            # simulate unavailable -> fallback
            stage = RNNoiseStage(sample_rate=16000, fallback=_FakeFallback())
            self.assertEqual(stage.backend, "fft")

        with patch("voice.rnnoise_stage._try_native") as try_native:
            native = _NativeRNNoise.__new__(_NativeRNNoise)
            native._denoiser = _FakeDenoise()
            native._up = bytearray()
            native._down = bytearray()
            native._leftover = []
            native._emitted = bytearray()
            try_native.return_value = native
            stage = RNNoiseStage(sample_rate=16000)
            self.assertEqual(stage.backend, "rnnoise")
            out = stage.process(_silence(1))
            self.assertGreater(len(out), 0)
            self.assertEqual(len(out) % 2, 0)

    def test_resampling_helpers_roundtrip(self) -> None:
        data = _as_bytes([0.0, 0.5, -0.5, 1.0, -1.0])
        floats = _as_float(data)
        self.assertAlmostEqual(floats[0], 0.0, places=4)
        self.assertAlmostEqual(floats[1], 0.5, places=4)
        self.assertAlmostEqual(floats[2], -0.5, places=4)

    def test_native_process_handles_partial_chunks(self) -> None:
        fake = _FakeRNNoiseModule()
        native = _NativeRNNoise.__new__(_NativeRNNoise)
        native._denoiser = _FakeDenoise()
        native._up = bytearray()
        native._down = bytearray()
        native._leftover = []
        native._emitted = bytearray()
        out = native.process(b"\x00\x00" * 8000)
        self.assertEqual(len(out) % 2, 0)
        native.reset()


if __name__ == "__main__":
    unittest.main()
