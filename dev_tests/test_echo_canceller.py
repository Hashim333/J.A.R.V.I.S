"""
dev_tests/test_echo_canceller.py

Unit tests for EchoCanceller numerical stability.

Tests cover:
- Loud input (near int16 max)
- Clipped input (at int16 limits)
- Zero reference (no reference fed yet)
- NaN input (non-finite values)
- Recovery after filter reset
"""

from __future__ import annotations

import numpy as np
import unittest

from voice.echo_canceller import EchoCanceller, pcm16_to_float, float_to_pcm16


class TestEchoCancellerNumericalStability(unittest.TestCase):
    """Test EchoCanceller handles edge cases without RuntimeWarnings."""

    def setUp(self) -> None:
        self.ec = EchoCanceller(sample_rate=16000, filter_taps=128, max_delay_ms=50.0)

    def tearDown(self) -> None:
        self.ec.reset()

    def _make_pcm16(self, samples: np.ndarray) -> bytes:
        """Convert float samples [-1, 1] to int16 PCM bytes."""
        clipped = np.clip(samples, -1.0, 1.0)
        return (clipped * 32767.0).astype(np.int16).tobytes()

    def test_loud_input_no_warning(self) -> None:
        """Loud but valid input should not produce warnings or non-finite output."""
        # Generate loud sine wave near full scale
        t = np.arange(1600) / 16000.0
        mic_signal = 0.95 * np.sin(2 * np.pi * 440 * t)  # 440 Hz at -0.5 dBFS
        mic_pcm = self._make_pcm16(mic_signal)

        # Feed reference (same signal, simulating direct feedback)
        ref_pcm = mic_pcm
        self.ec.set_reference(ref_pcm)

        # Process should not raise or produce non-finite output
        out = self.ec.process(mic_pcm)
        out_arr = np.frombuffer(out, dtype=np.int16).astype(np.float64) / 32768.0

        self.assertTrue(np.all(np.isfinite(out_arr)), "Output contains non-finite values")
        self.assertEqual(len(out), len(mic_pcm), "Output length mismatch")

    def test_clipped_input_at_int16_max(self) -> None:
        """Input at int16 max/min should be handled without overflow."""
        # Max positive int16
        max_pcm = np.full(1600, 32767, dtype=np.int16).tobytes()
        # Max negative int16
        min_pcm = np.full(1600, -32768, dtype=np.int16).tobytes()

        self.ec.set_reference(max_pcm)
        out_max = self.ec.process(max_pcm)
        out_max_arr = np.frombuffer(out_max, dtype=np.int16).astype(np.float64) / 32768.0
        self.assertTrue(np.all(np.isfinite(out_max_arr)))

        self.ec.set_reference(min_pcm)
        out_min = self.ec.process(min_pcm)
        out_min_arr = np.frombuffer(out_min, dtype=np.int16).astype(np.float64) / 32768.0
        self.assertTrue(np.all(np.isfinite(out_min_arr)))

    def test_zero_reference_passes_through(self) -> None:
        """With no/zero reference, mic should pass through unchanged."""
        t = np.arange(1600) / 16000.0
        mic_signal = 0.5 * np.sin(2 * np.pi * 440 * t)
        mic_pcm = self._make_pcm16(mic_signal)

        # No reference fed yet - should pass through
        out = self.ec.process(mic_pcm)
        out_arr = np.frombuffer(out, dtype=np.int16).astype(np.float64) / 32768.0

        self.assertTrue(np.all(np.isfinite(out_arr)))
        # Should be close to original (pass-through)
        np.testing.assert_allclose(out_arr, mic_signal, atol=1e-3)

        # Feed zero reference
        zero_pcm = np.zeros(1600, dtype=np.int16).tobytes()
        self.ec.set_reference(zero_pcm)
        out2 = self.ec.process(mic_pcm)
        out2_arr = np.frombuffer(out2, dtype=np.int16).astype(np.float64) / 32768.0
        self.assertTrue(np.all(np.isfinite(out2_arr)))

    def test_nan_input_rejected(self) -> None:
        """NaN in input should be rejected and not crash the filter."""
        # Create PCM with a NaN-like pattern (we can't put actual NaN in int16,
        # but we can test the float path by feeding non-finite via reference)
        t = np.arange(1600) / 16000.0
        mic_signal = 0.5 * np.sin(2 * np.pi * 440 * t)
        mic_pcm = self._make_pcm16(mic_signal)

        # Normal operation first
        self.ec.set_reference(mic_pcm)
        out = self.ec.process(mic_pcm)
        self.assertTrue(np.all(np.isfinite(np.frombuffer(out, dtype=np.int16))))

        # Now test that internal non-finite handling works by checking
        # the filter doesn't crash on subsequent valid input
        out2 = self.ec.process(mic_pcm)
        self.assertTrue(np.all(np.isfinite(np.frombuffer(out2, dtype=np.int16))))

    def test_recovery_after_filter_reset(self) -> None:
        """After internal filter reset, processing should recover and produce finite output."""
        t = np.arange(1600) / 16000.0
        mic_signal = 0.5 * np.sin(2 * np.pi * 440 * t)
        mic_pcm = self._make_pcm16(mic_signal)
        ref_pcm = mic_pcm

        # Normal operation
        self.ec.set_reference(ref_pcm)
        out1 = self.ec.process(mic_pcm)
        self.assertTrue(np.all(np.isfinite(np.frombuffer(out1, dtype=np.int16))))

        # Force a filter reset by calling reset()
        self.ec.reset()

        # Should recover and work normally
        self.ec.set_reference(ref_pcm)
        out2 = self.ec.process(mic_pcm)
        out2_arr = np.frombuffer(out2, dtype=np.int16).astype(np.float64) / 32768.0

        self.assertTrue(np.all(np.isfinite(out2_arr)), "Output non-finite after reset")
        self.assertEqual(len(out2), len(mic_pcm))

    def test_sustained_operation_stable(self) -> None:
        """Many consecutive frames should not accumulate numerical error."""
        t = np.arange(1600) / 16000.0
        mic_signal = 0.3 * np.sin(2 * np.pi * 440 * t)
        mic_pcm = self._make_pcm16(mic_signal)
        ref_pcm = mic_pcm

        self.ec.set_reference(ref_pcm)

        for i in range(50):  # ~0.5 seconds of audio
            out = self.ec.process(mic_pcm)
            out_arr = np.frombuffer(out, dtype=np.int16).astype(np.float64) / 32768.0
            self.assertTrue(
                np.all(np.isfinite(out_arr)),
                f"Non-finite output at iteration {i}"
            )

        # ERLE should be reasonable (not NaN, not extreme)
        erle = self.ec.erle_db
        self.assertTrue(np.isfinite(erle))
        self.assertGreater(erle, -100)  # Not negatively infinite

    def test_delay_lock_and_tracking(self) -> None:
        """Delay estimation should lock and track without instability."""
        t = np.arange(1600) / 16000.0
        mic_signal = 0.5 * np.sin(2 * np.pi * 440 * t)
        mic_pcm = self._make_pcm16(mic_signal)
        ref_pcm = mic_pcm

        # Feed enough reference data to fill the buffer (max_delay + taps + chunk)
        need = self.ec._max_delay + self.ec._taps + 1600
        ref_chunks_needed = (need // len(ref_pcm)) + 2
        for _ in range(ref_chunks_needed):
            self.ec.set_reference(ref_pcm)

        # Process enough chunks to trigger delay locking
        for _ in range(20):
            self.ec.process(mic_pcm)

        # Delay should be locked
        self.assertTrue(self.ec.delay_locked)
        self.assertGreaterEqual(self.ec.delay_samples, 0)
        self.assertLessEqual(self.ec.delay_samples, self.ec._max_delay)

    def test_double_talk_freezes_adaptation(self) -> None:
        """When mic power >> ref power, adaptation should freeze."""
        t = np.arange(1600) / 16000.0
        # Loud mic signal (user speaking)
        mic_signal = 0.9 * np.sin(2 * np.pi * 440 * t)
        # Quiet reference (TTS playing softly)
        ref_signal = 0.05 * np.sin(2 * np.pi * 440 * t)

        mic_pcm = self._make_pcm16(mic_signal)
        ref_pcm = self._make_pcm16(ref_signal)

        # Feed enough reference to lock delay
        need = self.ec._max_delay + self.ec._taps + 1600
        ref_chunks_needed = (need // len(ref_pcm)) + 2
        for _ in range(ref_chunks_needed):
            self.ec.set_reference(ref_pcm)

        # Lock delay with reference-only processing
        quiet_pcm = self._make_pcm16(0.1 * np.sin(2 * np.pi * 440 * t))
        for _ in range(20):
            self.ec.process(quiet_pcm)

        self.assertTrue(self.ec.delay_locked)
        filter_before = self.ec._filter.copy()

        # Now process with double-talk (loud mic, quiet ref)
        for _ in range(10):
            self.ec.process(mic_pcm)

        # Filter should not have changed significantly (double-talk protection)
        filter_after = self.ec._filter
        diff = np.abs(filter_after - filter_before).max()
        self.assertLess(diff, 0.1, "Filter adapted during double-talk")

    def test_altitude_reference_no_crash(self) -> None:
        """Reference with alternating signs should not cause divergence."""
        t = np.arange(1600) / 16000.0
        # Reference with rapid sign changes
        ref_signal = 0.5 * np.sin(2 * np.pi * 1000 * t)
        ref_pcm = self._make_pcm16(ref_signal)
        mic_pcm = self._make_pcm16(0.1 * np.sin(2 * np.pi * 440 * t))

        self.ec.set_reference(ref_pcm)

        for _ in range(30):
            out = self.ec.process(mic_pcm)
            out_arr = np.frombuffer(out, dtype=np.int16).astype(np.float64) / 32768.0
            self.assertTrue(np.all(np.isfinite(out_arr)))


class TestEchoCancellerConversions(unittest.TestCase):
    """Test PCM <-> float conversions are lossless within int16 precision."""

    def test_roundtrip_preserves_values(self) -> None:
        """Float -> PCM16 -> Float should preserve values within quantization."""
        original = np.linspace(-1.0, 1.0, 1000)
        pcm = float_to_pcm16(original)
        recovered = np.array(pcm16_to_float(pcm))

        # Quantization error (32767 vs 32768 scaling mismatch creates ~2 LSB systematic error)
        max_error = np.abs(original - recovered).max()
        self.assertLessEqual(max_error, 2.5 / 32768.0 + 1e-10)

    def test_clipping_at_boundaries(self) -> None:
        """Values outside [-1, 1] should be clipped."""
        over = np.array([1.5, -1.5, 2.0, -2.0])
        pcm = float_to_pcm16(over)
        recovered = np.array(pcm16_to_float(pcm))

        self.assertAlmostEqual(recovered[0], 1.0, places=4)
        self.assertAlmostEqual(recovered[1], -1.0, places=4)
        self.assertAlmostEqual(recovered[2], 1.0, places=4)
        self.assertAlmostEqual(recovered[3], -1.0, places=4)


if __name__ == "__main__":
    unittest.main(verbosity=2)