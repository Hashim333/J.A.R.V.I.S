"""
tests/test_noise_suppressor.py

Unit tests for voice/noise_suppressor.py — adaptive spectral noise
suppression: stationary noise is suppressed, non-stationary (speech-like)
signal is preserved, and silence stays silent.
"""

from __future__ import annotations

import unittest

import numpy as np

from voice.noise_suppressor import NoiseSuppressor


def _pcm(samples: np.ndarray) -> bytes:
    arr = np.clip(np.asarray(samples, dtype=np.float64), -1.0, 1.0) * 32767.0
    return arr.astype(np.int16).tobytes()


def _rms(data: bytes) -> float:
    if not data:
        return 0.0
    arr = np.frombuffer(data, dtype=np.int16).astype(np.float64) / 32768.0
    return float(np.sqrt(np.mean(arr * arr)))


def _silent_chunk(n_frames: int = 256) -> bytes:
    return b"\x00\x00" * n_frames


def _chirp(n_frames: int, sr: int = 16000, f0: float = 200.0, f1: float = 3000.0) -> np.ndarray:
    """Non-stationary sweep whose spectrum changes every frame (speech-like)."""
    t = np.arange(n_frames) / sr
    phase = 2 * np.pi * (f0 * t + 0.5 * (f1 - f0) / n_frames * t**2 * sr)
    return 0.4 * np.sin(phase)


class TestNoiseSuppressorSilence(unittest.TestCase):
    def test_silence_in_silence_out(self) -> None:
        ns = NoiseSuppressor(sample_rate=16000)
        outputs = []
        for _ in range(80):
            outputs.append(ns.process(_silent_chunk()))
        total = b"".join(outputs)
        self.assertLess(_rms(total), 1e-4)

    def test_empty_and_odd_chunks_pass_through(self) -> None:
        ns = NoiseSuppressor(sample_rate=16000)
        self.assertEqual(ns.process(b""), b"")
        self.assertEqual(ns.process(b"\x00"), b"\x00")

    def test_noise_floor_tracks(self) -> None:
        ns = NoiseSuppressor(sample_rate=16000)
        self.assertEqual(ns.noise_floor, 0.0)  # not initialized
        self.assertFalse(ns.initialized)
        for _ in range(40):
            ns.process(_silent_chunk())
        self.assertTrue(ns.initialized)


class TestNoiseSuppressorPreservation(unittest.TestCase):
    def test_speech_like_signal_is_preserved(self) -> None:
        """Non-stationary speech-like energy must survive suppression."""
        ns = NoiseSuppressor(sample_rate=16000)
        for _ in range(20):
            ns.process(_silent_chunk())

        chunk = _pcm(_chirp(1024))
        outputs = [ns.process(chunk)]
        for _ in range(30):
            outputs.append(ns.process(chunk))
        total = b"".join(outputs)

        in_rms = _rms(chunk)
        out_rms = _rms(total)
        self.assertGreater(in_rms, 0.0)
        # Meaningful fraction of the input survives (vs <1e-4 for silence).
        self.assertGreater(out_rms / in_rms, 0.25)

    def test_stationary_tone_is_suppressed(self) -> None:
        """A steady tone is tracked as noise and suppressed to the floor."""
        ns = NoiseSuppressor(sample_rate=16000)
        for _ in range(20):
            ns.process(_silent_chunk())

        t = np.arange(1024) / 16000.0
        chunk = _pcm(0.4 * np.sin(2 * np.pi * 440 * t))
        outputs = [ns.process(chunk)]
        for _ in range(30):
            outputs.append(ns.process(chunk))
        total = b"".join(outputs)

        out_rms = _rms(total)
        self.assertLess(out_rms, 0.2)

    def test_processing_is_length_preserving_after_latency(self) -> None:
        """Total emitted samples approach total input minus STFT latency."""
        ns = NoiseSuppressor(sample_rate=16000)
        chunk = _pcm(np.random.default_rng(7).standard_normal(512))
        fed = 0
        emitted = 0
        for _ in range(200):
            fed += len(chunk)
            emitted += len(ns.process(chunk))
        # Intrinsic STFT latency is frame_size - hop = 256 samples (512 bytes).
        latency_bytes = 256 * 2
        self.assertLessEqual(abs(emitted - (fed - latency_bytes)), 4)


if __name__ == "__main__":
    unittest.main()
