"""
tests/test_mic_preprocess.py

Unit tests for the FIX-003 microphone preprocessing upgrades added to
voice/microphone_processor.py:

  * DC-offset removal — a constant bias is driven toward zero,
  * high-pass filter — sub-cutoff rumble is attenuated while speech-band
    content is passed at unity gain,
  * adaptive noise gate — a measured noise floor raises the gate threshold
    so steady background is suppressed,
  * speech normalization — quiet-but-valid speech is lifted toward the
    target RMS so it clears the noise gate.
"""

from __future__ import annotations

import math
import struct
import unittest

from voice.microphone_processor import MicrophoneProcessor


def _sine_chunk(
    freq: float,
    amplitude: float,
    num_samples: int = 1024,
    rate: int = 16000,
) -> bytes:
    peak = int(amplitude * 32767)
    samples = [
        int(peak * math.sin(2.0 * math.pi * freq * i / rate)) for i in range(num_samples)
    ]
    return struct.pack("<" + "h" * len(samples), *samples)


def _dc_biased_chunk(offset: float, amplitude: float, num_samples: int = 1024) -> bytes:
    peak = int(amplitude * 32767)
    dc = int(offset * 32767)
    samples = [dc + (peak if i % 2 == 0 else -peak) for i in range(num_samples)]
    return struct.pack("<" + "h" * len(samples), *samples)


def _rms_of_chunk(chunk: bytes) -> float:
    import audioop
    return audioop.rms(chunk, 2) / 32768.0


def _mean_of_chunk(chunk: bytes) -> float:
    samples = struct.unpack("<%dh" % (len(chunk) // 2), chunk)
    return sum(samples) / len(samples) / 32768.0


def _is_silent(chunk: bytes) -> bool:
    return all(b == 0 for b in chunk)


def _plain() -> MicrophoneProcessor:
    return MicrophoneProcessor(
        agc_enabled=False,
        noise_gate_enabled=False,
        calibration_duration=0.0,
        normalization_target=1.0,
    )


class TestDCRemoval(unittest.TestCase):
    def test_dc_bias_is_removed(self) -> None:
        processor = _plain()
        processor.start()
        biased = _dc_biased_chunk(offset=0.2, amplitude=0.1)
        for _ in range(3):
            out = processor.process_chunk(biased)
        # After convergence the mean should be near zero (offset was 0.2).
        self.assertLess(abs(_mean_of_chunk(out)), 0.02)

    def test_dc_removal_disabled_keeps_bias(self) -> None:
        processor = MicrophoneProcessor(
            agc_enabled=False,
            noise_gate_enabled=False,
            calibration_duration=0.0,
            normalization_target=1.0,
            dc_removal_enabled=False,
            high_pass_enabled=False,
        )
        processor.start()
        biased = _dc_biased_chunk(offset=0.2, amplitude=0.0)
        out = processor.process_chunk(biased)
        self.assertGreater(abs(_mean_of_chunk(out)), 0.1)


class TestHighPass(unittest.TestCase):
    def test_low_frequency_rumble_attenuated(self) -> None:
        processor = _plain()
        processor.start()
        rumble = _sine_chunk(freq=20.0, amplitude=0.3)
        out = processor.process_chunk(rumble)
        self.assertLess(
            _rms_of_chunk(out), 0.3 * _rms_of_chunk(rumble),
            "20 Hz rumble should be attenuated below the 80 Hz cutoff",
        )

    def test_speech_band_passes_at_unity_gain(self) -> None:
        processor = _plain()
        processor.start()
        speech = _sine_chunk(freq=1000.0, amplitude=0.3)
        out = processor.process_chunk(speech)
        self.assertGreater(
            _rms_of_chunk(out), 0.8 * _rms_of_chunk(speech),
            "1 kHz speech content should pass the high-pass unchanged",
        )


class TestAdaptiveNoiseGate(unittest.TestCase):
    def test_noise_floor_raises_gate_threshold(self) -> None:
        processor = MicrophoneProcessor(
            agc_enabled=False,
            noise_gate_enabled=True,
            noise_gate_threshold=0.02,
            calibration_duration=0.1,
            normalization_target=1.0,
        )
        processor.start()
        quiet = _sine_chunk(freq=500.0, amplitude=0.05)
        for _ in range(5):
            processor.process_chunk(quiet)
        self.assertTrue(processor.calibrated)
        self.assertGreater(processor.noise_floor, 0.0)

        # A chunk near the old 0.02 threshold but below the raised gate is
        # suppressed (soft gate: attenuated, not hard-zeroed, so a soft
        # speech onset at the same level survives for Whisper); a
        # clearly-louder chunk passes.
        mid = _sine_chunk(freq=500.0, amplitude=0.06)
        gated = processor.process_chunk(mid)
        self.assertLess(
            _rms_of_chunk(gated), 0.5 * _rms_of_chunk(mid),
            "sub-gate noise should be strongly attenuated",
        )
        self.assertLess(
            _rms_of_chunk(gated), 0.02,
            "sub-gate noise must stay below the static threshold",
        )

        loud = _sine_chunk(freq=500.0, amplitude=0.09)
        passed = processor.process_chunk(loud)
        self.assertFalse(_is_silent(passed), "loud speech should pass the gate")

    def test_speech_during_calibration_does_not_raise_floor(self) -> None:
        """P0: the owner starts listening immediately, so the first second
        can contain user speech (observed: SPEECH DETECTED before
        calibration complete).  A median would lock the floor to speech
        RMS and desensitize the gate for the whole session; the 25th
        percentile keeps the quiet quartile instead."""
        processor = MicrophoneProcessor(
            agc_enabled=False,
            noise_gate_enabled=True,
            noise_gate_threshold=0.02,
            calibration_duration=1.0,  # 15 chunks at 1024/16 kHz
            normalization_target=1.0,
        )
        processor.start()
        loud = _sine_chunk(freq=500.0, amplitude=0.5)   # rms ~0.35 (speech)
        quiet = _sine_chunk(freq=500.0, amplitude=0.01)  # rms ~0.007 (room)
        for _ in range(11):
            processor.process_chunk(loud)
        for _ in range(4):
            processor.process_chunk(quiet)
        self.assertTrue(processor.calibrated)
        self.assertLess(
            processor.noise_floor, 0.02,
            "floor must track the quiet quartile, not speech "
            f"(got {processor.noise_floor:.4f})",
        )


class TestSpeechNormalization(unittest.TestCase):
    def test_quiet_speech_lifted_toward_target(self) -> None:
        processor = MicrophoneProcessor(
            agc_enabled=False,
            noise_gate_enabled=False,
            calibration_duration=0.0,
            normalization_target=1.0,
            speech_normalization_enabled=True,
            speech_target_rms=0.15,
        )
        processor.start()
        quiet = _sine_chunk(freq=500.0, amplitude=0.05)
        out = processor.process_chunk(quiet)
        self.assertGreater(
            _rms_of_chunk(out), 0.1,
            "quiet speech should be boosted toward the target RMS",
        )

    def test_loud_speech_not_boosted(self) -> None:
        processor = MicrophoneProcessor(
            agc_enabled=False,
            noise_gate_enabled=False,
            calibration_duration=0.0,
            normalization_target=1.0,
            speech_normalization_enabled=True,
            speech_target_rms=0.15,
        )
        processor.start()
        loud = _sine_chunk(freq=500.0, amplitude=0.3)
        out = processor.process_chunk(loud)
        # Already above the boost ceiling -> left alone (peak norm disabled).
        self.assertLess(abs(_rms_of_chunk(out) - _rms_of_chunk(loud)), 0.05)


if __name__ == "__main__":
    unittest.main()
