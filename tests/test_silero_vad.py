"""
tests/test_silero_vad.py

Unit tests for voice/silero_vad.py.

SileroVAD is exercised with an injected fake model (no torch/ONNX needed):
  * state machine parity with voice.vad.VAD — onset, min-speech, hangover,
    max-utterance,
  * per-frame speech probability gating via start/end thresholds,
  * noise-floor adaptation changes onset frames and threshold,
  * WebRTC VAD fallback when no model is injected and auto_load=False,
  * background loading never blocks the constructor.
"""

from __future__ import annotations

import threading
import time
import unittest

from voice.silero_vad import SileroVAD, _SILERO_FRAME_BYTES


class FakeSilero:
    """Returns a fixed speech probability per call."""

    def __init__(self, probability: float = 0.9) -> None:
        self.probability = probability
        self.calls = 0

    def __call__(self, tensor, sample_rate: int) -> float:
        self.calls += 1
        return self.probability


def _feed(vad: SileroVAD, frames: int, prob_model: FakeSilero) -> None:
    # every 512-sample frame -> int16 PCM bytes
    frame = b"\x00\x00" * 512  # 1024 bytes = one 512-sample Silero frame
    for _ in range(frames):
        prob_model.probability = prob_model.probability
        vad.process_audio(frame)


class TestSileroStateMachine(unittest.TestCase):
    def test_onset_requires_n_consecutive_speech_frames(self) -> None:
        model = FakeSilero(0.9)
        started = []
        vad = SileroVAD(
            model=model,
            on_speech_started=lambda: started.append(True),
            silence_hangover_ms=320.0,
            min_speech_ms=250.0,
            onset_frames=3,
            auto_load=False,
        )
        _feed(vad, 2, model)
        self.assertFalse(vad.triggered)
        _feed(vad, 1, model)
        self.assertTrue(vad.triggered)
        self.assertEqual(len(started), 1)

    def test_low_probability_frames_never_trigger(self) -> None:
        model = FakeSilero(0.1)
        vad = SileroVAD(
            model=model,
            onset_frames=3,
            silence_hangover_ms=320.0,
            auto_load=False,
        )
        _feed(vad, 10, model)
        self.assertFalse(vad.triggered)

    def test_hangover_ends_speech_after_silent_frames(self) -> None:
        model = FakeSilero(0.9)
        ended = []
        vad = SileroVAD(
            model=model,
            on_speech_ended=lambda: ended.append(True),
            silence_hangover_ms=320.0,
            min_speech_ms=250.0,
            onset_frames=3,
            auto_load=False,
        )
        _feed(vad, 3, model)  # trigger
        _feed(vad, 5, model)  # speaking
        model.probability = 0.1
        _feed(vad, 10, model)  # silent past hangover (10 frames > 10 needed)
        self.assertFalse(vad.triggered)
        self.assertEqual(len(ended), 1)

    def test_max_utterance_force_ends(self) -> None:
        model = FakeSilero(0.9)
        ended = []
        vad = SileroVAD(
            model=model,
            on_speech_ended=lambda: ended.append(True),
            silence_hangover_ms=320.0,
            min_speech_ms=250.0,
            max_utterance_ms=320.0,  # 10 frames
            onset_frames=1,
            auto_load=False,
        )
        _feed(vad, 12, model)
        # force-end fires once (continuous speech may then re-trigger,
        # exactly like the reference voice.vad.VAD)
        self.assertEqual(len(ended), 1)

    def test_backend_reports_silero_for_injected_model(self) -> None:
        vad = SileroVAD(model=FakeSilero(), auto_load=False)
        self.assertEqual(vad.backend, "silero")


class TestSileroNoiseFloor(unittest.TestCase):
    def test_quiet_noise_keeps_default_onset(self) -> None:
        vad = SileroVAD(model=FakeSilero(), auto_load=False)
        vad.set_noise_floor(0.001)
        self.assertEqual(vad.onset_frames, 3)

    def test_noisy_floor_raises_onset_and_threshold(self) -> None:
        vad = SileroVAD(model=FakeSilero(), auto_load=False)
        vad.set_noise_floor(0.08)
        self.assertEqual(vad.onset_frames, 6)
        self.assertGreaterEqual(vad._start_threshold, 0.8)


class TestSileroFallback(unittest.TestCase):
    def test_no_model_uses_webrtc_delegate(self) -> None:
        vad = SileroVAD(auto_load=False)
        self.assertEqual(vad.backend, "webrtc")
        self.assertIsNotNone(vad._delegate)

    def test_background_load_starts_thread_and_stays_webrtc(self) -> None:
        vad = SileroVAD(auto_load=True)
        self.assertEqual(vad.backend, "webrtc")
        self.assertIsNotNone(vad._load_thread)
        self.assertTrue(vad._load_thread.daemon)
        # give the loader a moment; it must never crash the test
        time.sleep(0.2)
        vad.reset()

    def test_reset_keeps_backend(self) -> None:
        vad = SileroVAD(model=FakeSilero(), auto_load=False)
        vad.reset()
        self.assertFalse(vad.triggered)
        self.assertEqual(vad.backend, "silero")

    def test_frame_probability_uses_16k_int16(self) -> None:
        model = FakeSilero(0.9)
        vad = SileroVAD(model=model, auto_load=False)
        vad.process_audio(b"\x00\x00" * 512)
        self.assertEqual(model.calls, 1)


if __name__ == "__main__":
    unittest.main()
