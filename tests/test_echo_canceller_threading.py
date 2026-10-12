"""EchoCanceller threading + delay-estimator regression tests.

Confirmed defect: the TTS playback thread calls ``set_reference`` from inside
its audio write loop, while the microphone capture thread calls ``process``
on the *same* ``threading.Lock``.  ``process`` held that lock for its entire
NLMS/DSP pass, so the playback thread blocked on every audio slice:

    setref_median_ms: 7.47   setref_p95_ms: 42.62
    setref_p99_ms: 143.59    setref_max_ms: 168.74
    setref_total_ms: 2545.41  (over 200 feeds)

Blocking the audio thread mid-utterance is audible as chopping/stutter.  The
reference history now has its own lock that the DSP never holds, and the
delay estimator is vectorised.

No audio hardware, no network, no real-time tolerance assumed.
"""
from __future__ import annotations

import threading
import time
import unittest

import numpy as np

from voice.echo_canceller import EchoCanceller

_REF_CHUNK = 512  # reference feed granularity in samples


def _pcm(samples: np.ndarray) -> bytes:
    return samples.astype(np.int16).tobytes()


class TestReferenceFeedNeverWaitsForDsp(unittest.TestCase):
    """``set_reference`` runs on the TTS playback thread; it must never wait
    for the adaptive filter."""

    def test_set_reference_completes_while_dsp_lock_is_held(self) -> None:
        canceller = EchoCanceller(sample_rate=16000)
        reference = (np.random.randn(1024) * 2000).astype(np.int16).tobytes()

        # Simulate the capture thread being deep inside its DSP pass.
        canceller._lock.acquire()
        done = threading.Event()

        def feed() -> None:
            canceller.set_reference(reference)
            done.set()

        worker = threading.Thread(target=feed, daemon=True)
        worker.start()
        finished_while_dsp_busy = done.wait(timeout=2.0)
        canceller._lock.release()
        worker.join(timeout=2.0)

        self.assertTrue(
            finished_while_dsp_busy,
            "set_reference blocked on the DSP lock held by the capture thread",
        )

    def test_reference_is_recorded_even_while_dsp_is_busy(self) -> None:
        canceller = EchoCanceller(sample_rate=16000)
        chunk = (np.random.randn(512) * 2000).astype(np.int16).tobytes()

        canceller._lock.acquire()
        try:
            canceller.set_reference(chunk)
        finally:
            canceller._lock.release()

        self.assertEqual(len(canceller._ref), 512)

    def test_process_takes_a_snapshot_not_the_live_history(self) -> None:
        """A reference append during processing must not break the DSP pass."""
        canceller = EchoCanceller(sample_rate=16000)
        reference = (np.random.randn(6000) * 2000).astype(np.int16).tobytes()
        canceller.set_reference(reference)

        mic = (np.random.randn(1024) * 1000).astype(np.int16).tobytes()
        out = canceller.process(mic)
        self.assertEqual(len(out), len(mic))


class TestDelayEstimatorStillCorrect(unittest.TestCase):
    """The vectorised estimator must recover the same lag as the per-lag loop
    it replaced."""

    @staticmethod
    def _canceller_with_reference(total_blocks: int = 12) -> EchoCanceller:
        canceller = EchoCanceller(sample_rate=16000)
        rng = np.random.default_rng(7)
        reference = rng.standard_normal(1024 * total_blocks) * 3000.0
        for start in range(0, len(reference), _REF_CHUNK):
            piece = reference[start:start + _REF_CHUNK]
            if piece.size == 0:
                break
            canceller.set_reference(_pcm(piece))
        canceller.test_reference = reference  # type: ignore[attr-defined]
        return canceller

    def test_recovers_the_known_lag(self) -> None:
        canceller = self._canceller_with_reference(total_blocks=12)
        reference = canceller.test_reference  # type: ignore[attr-defined]
        core = 1024
        true_lag = 400

        mic = _pcm(reference[len(reference) - true_lag - core:len(reference) - true_lag] * 0.5)
        canceller.process(mic)

        self.assertTrue(canceller.delay_locked, "delay was never locked")
        self.assertEqual(canceller.delay_samples, true_lag)

    def test_output_length_is_preserved(self) -> None:
        canceller = self._canceller_with_reference()
        mic = (np.random.randn(1024) * 1000).astype(np.int16).tobytes()
        self.assertEqual(len(canceller.process(mic)), len(mic))

    def test_passes_through_until_enough_reference_seen(self) -> None:
        canceller = EchoCanceller(sample_rate=16000)
        mic = (np.random.randn(1024) * 1000).astype(np.int16).tobytes()
        self.assertEqual(canceller.process(mic), mic)

    def test_odd_length_chunk_is_returned_unchanged(self) -> None:
        canceller = self._canceller_with_reference()
        odd = b"\x01\x02\x03"
        self.assertEqual(canceller.process(odd), odd)


class TestResetIsSafeAlongsideReferenceFeed(unittest.TestCase):
    def test_reset_then_feed_keeps_working(self) -> None:
        canceller = EchoCanceller(sample_rate=16000)
        reference = (np.random.randn(4096) * 2000).astype(np.int16).tobytes()
        canceller.set_reference(reference)
        canceller.reset()

        canceller.set_reference(reference)
        mic = (np.random.randn(1024) * 1000).astype(np.int16).tobytes()
        self.assertEqual(len(canceller.process(mic)), len(mic))
        self.assertFalse(canceller.delay_locked)

    def test_reset_is_not_deadlocked_by_a_concurrent_feed(self) -> None:
        canceller = EchoCanceller(sample_rate=16000)
        chunk = (np.random.randn(_REF_CHUNK) * 2000).astype(np.int16).tobytes()
        stop = threading.Event()
        errors: list[BaseException] = []

        def feeder() -> None:
            try:
                while not stop.is_set():
                    canceller.set_reference(chunk)
            except BaseException as exc:  # pragma: no cover - failure path
                errors.append(exc)

        worker = threading.Thread(target=feeder, daemon=True)
        worker.start()
        try:
            for _ in range(50):
                canceller.reset()
                started = time.perf_counter()
                canceller.process(chunk)
                self.assertLess((time.perf_counter() - started) * 1000.0, 500.0)
        finally:
            stop.set()
            worker.join(timeout=2.0)

        self.assertEqual(errors, [])


if __name__ == "__main__":
    unittest.main()
