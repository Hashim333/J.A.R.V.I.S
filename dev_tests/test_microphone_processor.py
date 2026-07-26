"""
dev_tests/test_microphone_processor.py

Unit tests for the MicrophoneProcessor pipeline:
AGC, noise gate, normalization, auto-calibration, audio level.
"""
import struct
import unittest

from voice.microphone_processor import MicrophoneProcessor


def _make_chunk(rms_amplitude: float, num_samples: int = 1024) -> bytes:
    """Generate a 16-bit mono PCM chunk with a given RMS amplitude (0-32767)."""
    max_val = int(rms_amplitude * 32767)
    samples = [max_val if i % 2 == 0 else -max_val for i in range(num_samples)]
    return struct.pack("<" + "h" * num_samples, *samples)


def _silent_chunk(num_samples: int = 1024) -> bytes:
    return b'\x00' * (num_samples * 2)


def _rms_of_chunk(chunk: bytes) -> float:
    import audioop
    return audioop.rms(chunk, 2) / 32768.0


class TestMicrophoneProcessor(unittest.TestCase):
    """Test cases for the audio processing pipeline."""

    def setUp(self):
        self.processor = MicrophoneProcessor(
            sensitivity=1.0,
            agc_enabled=True,
            agc_target_level=0.15,
            agc_max_gain=10.0,
            noise_gate_enabled=True,
            noise_gate_threshold=0.02,
            calibration_duration=0.0,  # skip calibration in most tests
        )

    # ── Basic processing ──────────────────────────────────────────────

    def test_returns_same_size_chunk(self) -> None:
        self.processor.start()
        chunk = _make_chunk(0.1)
        result = self.processor.process_chunk(chunk)
        self.assertEqual(len(result), len(chunk))

    def test_silent_chunk_unchanged(self) -> None:
        self.processor.start()
        chunk = _silent_chunk()
        result = self.processor.process_chunk(chunk)
        self.assertEqual(result, chunk)

    def test_empty_chunk_returns_empty(self) -> None:
        self.processor.start()
        self.assertEqual(self.processor.process_chunk(b''), b'')

    # ── Noise gate ────────────────────────────────────────────────────

    def test_noise_gate_suppresses_low_audio(self) -> None:
        self.processor.start()
        chunk = _make_chunk(0.001)
        result = self.processor.process_chunk(chunk)
        self.assertTrue(all(b == 0 for b in result))

    def test_noise_gate_passes_loud_audio(self) -> None:
        self.processor.start()
        chunk = _make_chunk(0.1)
        result = self.processor.process_chunk(chunk)
        rms = _rms_of_chunk(result)
        self.assertGreater(rms, 0.02, "Noise gate should not suppress loud audio")

    # ── AGC ───────────────────────────────────────────────────────────

    def test_agc_amplifies_quiet_audio(self) -> None:
        processor = MicrophoneProcessor(
            agc_enabled=True,
            agc_target_level=0.15,
            noise_gate_enabled=False,
            calibration_duration=0.0,
        )
        processor.start()
        quiet = _make_chunk(0.01)
        result = processor.process_chunk(quiet)
        rms = _rms_of_chunk(result)
        self.assertGreater(rms, 0.01, "AGC should amplify quiet audio")

    def test_agc_approaches_target_level(self) -> None:
        processor = MicrophoneProcessor(
            agc_enabled=True,
            agc_target_level=0.2,
            agc_max_gain=10.0,
            agc_attack=1.0,  # instant adaptation
            agc_release=1.0,
            noise_gate_enabled=False,
            calibration_duration=0.0,
        )
        processor.start()
        chunk = _make_chunk(0.02)
        for _ in range(10):
            result = processor.process_chunk(chunk)
        rms = _rms_of_chunk(result)
        self.assertAlmostEqual(rms, 0.2, delta=0.05,
                               msg="AGC should converge to target level")

    def test_agc_disabled_does_not_change_gain(self) -> None:
        processor = MicrophoneProcessor(
            agc_enabled=False,
            noise_gate_enabled=False,
            calibration_duration=0.0,
        )
        processor.start()
        chunk = _make_chunk(0.1)
        original_rms = _rms_of_chunk(chunk)
        result = processor.process_chunk(chunk)
        rms = _rms_of_chunk(result)
        self.assertAlmostEqual(rms, original_rms, delta=0.01,
                               msg="AGC disabled should not change gain")

    # ── Normalization ─────────────────────────────────────────────────

    def test_normalization_reduces_peak(self) -> None:
        processor = MicrophoneProcessor(
            agc_enabled=False,
            noise_gate_enabled=False,
            normalization_target=0.5,
            calibration_duration=0.0,
        )
        processor.start()
        loud = _make_chunk(0.9)
        result = processor.process_chunk(loud)
        peak = processor._calc_peak(result)
        self.assertLessEqual(peak, 0.55, "Normalization should reduce peak")

    # ── Calibration ───────────────────────────────────────────────────

    def test_calibration_sets_noise_floor(self) -> None:
        processor = MicrophoneProcessor(
            calibration_duration=0.1,  # very short calibration
            sample_rate=16000,
        )
        processor.start()
        quiet = _make_chunk(0.005)
        for _ in range(10):
            processor.process_chunk(quiet)
        self.assertTrue(processor.calibrated)
        self.assertGreater(processor.noise_floor, 0.0)

    def test_calibration_median_is_representative(self) -> None:
        processor = MicrophoneProcessor(
            calibration_duration=0.1,
            sample_rate=16000,
        )
        processor.start()
        for _ in range(5):
            processor.process_chunk(_make_chunk(0.01))
        self.assertTrue(processor.calibrated)
        self.assertAlmostEqual(processor.noise_floor, 0.01, delta=0.005)

    def test_zero_calibration_duration_skips_calibration(self) -> None:
        self.processor.start()
        self.assertTrue(self.processor.calibrated)
        self.assertEqual(self.processor.noise_floor, 0.0)

    # ── Audio level ───────────────────────────────────────────────────

    def test_audio_level_increases_with_volume(self) -> None:
        self.processor.start()
        self.processor.process_chunk(_make_chunk(0.001))
        low_level = self.processor.audio_level
        self.processor.process_chunk(_make_chunk(0.5))
        high_level = self.processor.audio_level
        self.assertGreater(high_level, low_level,
                           "Audio level should increase with volume")

    def test_audio_level_in_range(self) -> None:
        self.processor.start()
        for amp in [0.001, 0.01, 0.1, 0.5, 0.9]:
            self.processor.process_chunk(_make_chunk(amp))
            self.assertGreaterEqual(self.processor.audio_level, 0.0)
            self.assertLessEqual(self.processor.audio_level, 1.0)

    def test_silence_has_zero_audio_level(self) -> None:
        self.processor.start()
        self.processor.process_chunk(_silent_chunk())
        self.assertEqual(self.processor.audio_level, 0.0)

    # ── Properties ────────────────────────────────────────────────────

    def test_is_speech_true_when_above_threshold(self) -> None:
        self.processor.start()
        self.processor.process_chunk(_make_chunk(0.1))
        self.assertTrue(self.processor.is_speech)

    def test_is_speech_false_when_silent(self) -> None:
        self.processor.start()
        self.processor.process_chunk(_silent_chunk())
        self.assertFalse(self.processor.is_speech)

    def test_signal_to_noise_returns_ratio(self) -> None:
        self.processor.start()
        self.processor.process_chunk(_make_chunk(0.1))
        self.assertGreater(self.processor.signal_to_noise, 0.0)

    def test_signal_to_noise_is_one_when_not_calibrated(self) -> None:
        processor = MicrophoneProcessor(
            calibration_duration=0.0, noise_gate_enabled=False
        )
        processor.start()
        self.assertEqual(processor.signal_to_noise, 1.0)

    # ── Sensitivity ───────────────────────────────────────────────────

    def test_sensitivity_scales_audio(self) -> None:
        processor = MicrophoneProcessor(
            sensitivity=2.0,
            agc_enabled=False,
            noise_gate_enabled=False,
            calibration_duration=0.0,
        )
        processor.start()
        chunk = _make_chunk(0.1)
        result = processor.process_chunk(chunk)
        rms = _rms_of_chunk(result)
        self.assertAlmostEqual(rms, 0.2, delta=0.02,
                               msg="Sensitivity 2.0 should double RMS")

    # ── Lifecycle ─────────────────────────────────────────────────────

    def test_start_is_idempotent(self) -> None:
        self.processor.start()
        self.processor.start()
        self.processor.start()
        self.assertTrue(self.processor.calibrated)

    def test_shutdown_resets_state(self) -> None:
        self.processor.start()
        self.processor.process_chunk(_make_chunk(0.5))
        self.processor.shutdown()
        self.assertFalse(self.processor.calibrated)
        self.assertEqual(self.processor.audio_level, 0.0)
        self.assertEqual(self.processor.current_gain, 1.0)


if __name__ == "__main__":
    unittest.main()
