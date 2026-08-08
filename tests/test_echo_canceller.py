"""
tests/test_echo_canceller.py

Unit tests for voice/echo_canceller.py — reference-based NLMS echo
cancellation: pass-through until a delay is locked, then the speaker's
reference is cancelled from the microphone signal, and double-talk
freezes adaptation.
"""

from __future__ import annotations

import unittest

import numpy as np

from voice.echo_canceller import EchoCanceller


def _pcm(samples: np.ndarray) -> bytes:
    arr = np.clip(np.asarray(samples, dtype=np.float64), -1.0, 1.0) * 32767.0
    return arr.astype(np.int16).tobytes()


def _rms(data: bytes) -> float:
    if not data:
        return 0.0
    arr = np.frombuffer(data, dtype=np.int16).astype(np.float64) / 32768.0
    return float(np.sqrt(np.mean(arr * arr)))


def _make_canceller(**kwargs) -> EchoCanceller:
    defaults = dict(
        sample_rate=16000,
        filter_taps=64,
        max_delay_ms=10.0,
        lock_score=0.7,
    )
    defaults.update(kwargs)
    return EchoCanceller(**defaults)


class TestEchoCancellerPassThrough(unittest.TestCase):
    def test_returns_input_until_enough_reference(self) -> None:
        ec = _make_canceller()
        rng = np.random.default_rng(1)
        ref = rng.standard_normal(400)  # fewer than max_delay + taps + n samples
        ec.set_reference(_pcm(ref))
        chunk = _pcm(rng.standard_normal(256))
        self.assertEqual(ec.process(chunk), chunk)
        self.assertFalse(ec.delay_locked)

    def test_empty_chunk_passes_through(self) -> None:
        ec = _make_canceller()
        self.assertEqual(ec.process(b""), b"")


class TestEchoCancellerCancellation(unittest.TestCase):
    def test_locks_delay_and_cancels_echo(self) -> None:
        ec = _make_canceller()
        rng = np.random.default_rng(42)
        ref = rng.standard_normal(8192)
        ec.set_reference(_pcm(ref))

        delay = 50
        n = 256
        mic = ref[8192 - delay - n: 8192 - delay]
        mic_bytes = _pcm(mic)

        # First call locks the delay but cannot cancel yet.
        ec.process(mic_bytes)
        self.assertTrue(ec.delay_locked)
        self.assertEqual(ec.delay_samples, delay)

        rms_in = _rms(mic_bytes)
        last_out = b""
        for _ in range(60):
            last_out = ec.process(mic_bytes)
        rms_out = _rms(last_out)

        self.assertGreater(rms_in, 0.01)
        self.assertLess(rms_out, 0.05 * rms_in)
        self.assertGreater(ec.erle_db, 10.0)

    def test_double_talk_freezes_adaptation(self) -> None:
        """Loud user speech (mic >> reference) flags double-talk."""
        ec = _make_canceller()
        rng = np.random.default_rng(3)
        ref = 0.05 * rng.standard_normal(8192)  # quiet speaker reference
        ec.set_reference(_pcm(ref))

        delay = 40
        n = 256
        mic = ref[8192 - delay - n: 8192 - delay]
        ec.process(_pcm(mic))  # lock delay
        self.assertTrue(ec.delay_locked)

        loud = 0.5 * rng.standard_normal(n)
        ec.process(_pcm(loud))
        self.assertTrue(ec.double_talk)


class TestEchoCancellerReset(unittest.TestCase):
    def test_reset_clears_state(self) -> None:
        ec = _make_canceller()
        rng = np.random.default_rng(5)
        ref = rng.standard_normal(8192)
        ec.set_reference(_pcm(ref))

        delay = 40
        n = 256
        mic = ref[8192 - delay - n: 8192 - delay]
        ec.process(_pcm(mic))
        self.assertTrue(ec.delay_locked)

        ec.reset()
        self.assertFalse(ec.delay_locked)
        self.assertEqual(ec.erle_db, 0.0)
        self.assertFalse(ec.is_ready)


if __name__ == "__main__":
    unittest.main()
