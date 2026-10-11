"""
dev_tests/test_five_turn_stress.py

Stress test: 5 back-to-back voice turns through the echo canceller
and duplex session to verify:
1. No RuntimeWarnings (overflow, divide by zero, invalid values)
2. Echo canceller filter remains stable (no NaN/inf)
3. Recovery after filter reset works
"""

from __future__ import annotations

import numpy as np
import warnings
import unittest

from voice.echo_canceller import EchoCanceller
from voice.duplex import DuplexVoiceSession
from voice.rnnoise_stage import RNNoiseStage
from voice.silero_vad import SileroVAD


class TestFiveTurnStress(unittest.TestCase):
    """Stress test for 5 consecutive voice turns."""

    def setUp(self) -> None:
        # Capture warnings
        self._warnings = []
        self._old_showwarning = warnings.showwarning
        warnings.showwarning = self._capture_warning
        warnings.simplefilter("always")

    def tearDown(self) -> None:
        warnings.showwarning = self._old_showwarning
        warnings.simplefilter("default")

    def _capture_warning(self, message, category, filename, lineno, file=None, line=None):
        self._warnings.append((str(message), category.__name__, filename, lineno))

    def _make_pcm16(self, samples: np.ndarray) -> bytes:
        """Convert float samples [-1, 1] to int16 PCM bytes."""
        clipped = np.clip(samples, -1.0, 1.0)
        return (clipped * 32767.0).astype(np.int16).tobytes()

    def test_echo_canceller_five_turns_no_warnings(self):
        """Run 5 simulated turns through EchoCanceller - no RuntimeWarnings."""
        ec = EchoCanceller(sample_rate=16000, filter_taps=128, max_delay_ms=50.0)
        
        # Generate test signals for 5 turns
        turn_duration = 1.0  # 1 second per turn
        samples_per_turn = int(16000 * turn_duration)
        
        runtime_warnings = []
        
        for turn in range(5):
            # Simulate TTS reference (what JARVIS speaks)
            t = np.arange(samples_per_turn) / 16000.0
            ref_signal = 0.5 * np.sin(2 * np.pi * (440 + turn * 100) * t)
            ref_pcm = self._make_pcm16(ref_signal)
            
            # Feed reference in chunks (as TTS would)
            chunk_size = 1600  # 100ms chunks
            for i in range(0, len(ref_pcm), chunk_size):
                ec.set_reference(ref_pcm[i:i+chunk_size])
            
            # Simulate mic input (reference + some user speech + noise)
            mic_signal = ref_signal * 0.3 + 0.1 * np.sin(2 * np.pi * 880 * t) + 0.01 * np.random.randn(samples_per_turn)
            mic_pcm = self._make_pcm16(mic_signal)
            
            # Process in chunks (as microphone stream would)
            for i in range(0, len(mic_pcm), chunk_size):
                out = ec.process(mic_pcm[i:i+chunk_size])
                out_arr = np.frombuffer(out, dtype=np.int16).astype(np.float64) / 32768.0
                
                # Check for non-finite output
                if not np.all(np.isfinite(out_arr)):
                    self.fail(f"Turn {turn}: EchoCanceller produced non-finite output")
            
            # Verify filter is still finite
            if not np.all(np.isfinite(ec._filter)):
                self.fail(f"Turn {turn}: EchoCanceller filter went non-finite")
            
            # Reset for next turn (simulates capture_command ending)
            ec.reset()
        
        # Check for RuntimeWarnings
        runtime_warnings = [w for w in self._warnings if w[1] == 'RuntimeWarning']
        overflow_warnings = [w for w in runtime_warnings if 'overflow' in w[0].lower()]
        div_zero_warnings = [w for w in runtime_warnings if 'divide' in w[0].lower() and 'zero' in w[0].lower()]
        invalid_warnings = [w for w in runtime_warnings if 'invalid' in w[0].lower()]
        
        self.assertEqual(len(overflow_warnings), 0, f"Overflow warnings: {overflow_warnings}")
        self.assertEqual(len(div_zero_warnings), 0, f"Divide by zero warnings: {div_zero_warnings}")
        self.assertEqual(len(invalid_warnings), 0, f"Invalid value warnings: {invalid_warnings}")

    def test_duplex_session_five_turns(self):
        """Run 5 simulated turns through DuplexVoiceSession."""
        # Use a simple mock VAD/transcriber for testing
        session = DuplexVoiceSession(sample_rate=16000)
        
        turn_duration = 0.5  # 0.5 seconds per turn
        samples_per_turn = int(16000 * turn_duration)
        chunk_size = 1600
        
        runtime_warnings = []
        
        for turn in range(5):
            # Simulate TTS playing (feed reference)
            t = np.arange(samples_per_turn) / 16000.0
            ref_signal = 0.5 * np.sin(2 * np.pi * (440 + turn * 100) * t)
            ref_pcm = self._make_pcm16(ref_signal)
            
            # Feed reference in chunks
            for i in range(0, len(ref_pcm), chunk_size):
                session.feed_playback_reference(ref_pcm[i:i+chunk_size], sample_rate=16000)
            
            # Simulate mic input with echo
            mic_signal = ref_signal * 0.3 + 0.1 * np.sin(2 * np.pi * 880 * t) + 0.01 * np.random.randn(samples_per_turn)
            mic_pcm = self._make_pcm16(mic_signal)
            
            # Process through duplex session
            for i in range(0, len(mic_pcm), chunk_size):
                chunk = mic_pcm[i:i+chunk_size]
                try:
                    session.process_chunk(chunk)
                except Exception as exc:
                    self.fail(f"Turn {turn}: process_chunk raised {exc}")
            
            # Simulate capture turn
            session._capture_vad.reset()
            session._barge_in_vad.reset()
            session._echo_canceller.reset()
            session._noise_suppressor.reset()
        
        # Check for RuntimeWarnings
        runtime_warnings = [w for w in self._warnings if w[1] == 'RuntimeWarning']
        overflow_warnings = [w for w in runtime_warnings if 'overflow' in w[0].lower()]
        div_zero_warnings = [w for w in runtime_warnings if 'divide' in w[0].lower() and 'zero' in w[0].lower()]
        invalid_warnings = [w for w in runtime_warnings if 'invalid' in w[0].lower()]
        
        self.assertEqual(len(overflow_warnings), 0, f"Overflow warnings: {overflow_warnings}")
        self.assertEqual(len(div_zero_warnings), 0, f"Divide by zero warnings: {div_zero_warnings}")
        self.assertEqual(len(invalid_warnings), 0, f"Invalid value warnings: {invalid_warnings}")

    def test_loud_clipped_input_recovery(self):
        """Test recovery after loud/clipped input that could cause instability."""
        ec = EchoCanceller(sample_rate=16000, filter_taps=128, max_delay_ms=50.0)
        
        # Turn 1: Normal
        t = np.arange(1600) / 16000.0
        ref = self._make_pcm16(0.5 * np.sin(2 * np.pi * 440 * t))
        mic = self._make_pcm16(0.5 * np.sin(2 * np.pi * 440 * t) + 0.1 * np.random.randn(1600))
        
        for i in range(0, len(ref), 1600):
            ec.set_reference(ref)
        for i in range(0, len(mic), 1600):
            out = ec.process(mic)
            self.assertTrue(np.all(np.isfinite(np.frombuffer(out, dtype=np.int16))))
        ec.reset()
        
        # Turn 2: Very loud (near clipping)
        ref_loud = self._make_pcm16(0.99 * np.sin(2 * np.pi * 440 * t))
        mic_loud = self._make_pcm16(0.99 * np.sin(2 * np.pi * 440 * t))
        
        for i in range(0, len(ref_loud), 1600):
            ec.set_reference(ref_loud)
        for i in range(0, len(mic_loud), 1600):
            out = ec.process(mic_loud)
            self.assertTrue(np.all(np.isfinite(np.frombuffer(out, dtype=np.int16))))
        ec.reset()
        
        # Turn 3: Clipped (at int16 limits)
        clipped_signal = np.full(1600, 0.999)
        clipped_pcm = self._make_pcm16(clipped_signal)
        
        for i in range(0, len(clipped_pcm), 1600):
            ec.set_reference(clipped_pcm)
        for i in range(0, len(clipped_pcm), 1600):
            out = ec.process(clipped_pcm)
            self.assertTrue(np.all(np.isfinite(np.frombuffer(out, dtype=np.int16))))
        ec.reset()
        
        # Turn 4: Zero reference
        zero_pcm = self._make_pcm16(np.zeros(1600))
        normal_mic = self._make_pcm16(0.3 * np.sin(2 * np.pi * 440 * t))
        
        for i in range(0, len(zero_pcm), 1600):
            ec.set_reference(zero_pcm)
        for i in range(0, len(normal_mic), 1600):
            out = ec.process(normal_mic)
            self.assertTrue(np.all(np.isfinite(np.frombuffer(out, dtype=np.int16))))
        ec.reset()
        
        # Turn 5: Normal again (recovery)
        for i in range(0, len(ref), 1600):
            ec.set_reference(ref)
        for i in range(0, len(mic), 1600):
            out = ec.process(mic)
            self.assertTrue(np.all(np.isfinite(np.frombuffer(out, dtype=np.int16))))
        
        # Final filter check
        self.assertTrue(np.all(np.isfinite(ec._filter)))

    def test_concurrent_reference_and_process(self):
        """Test that reference feeding and processing can happen concurrently."""
        import threading
        import time
        
        ec = EchoCanceller(sample_rate=16000, filter_taps=128, max_delay_ms=50.0)
        errors = []
        
        def feed_reference():
            try:
                t = np.arange(16000) / 16000.0  # 1 second
                ref = 0.5 * np.sin(2 * np.pi * 440 * t)
                ref_pcm = self._make_pcm16(ref)
                for i in range(0, len(ref_pcm), 1600):
                    ec.set_reference(ref_pcm[i:i+1600])
                    time.sleep(0.001)  # Small delay
            except Exception as exc:
                errors.append(f"Reference feed error: {exc}")
        
        def process_mic():
            try:
                time.sleep(0.05)  # Let some reference accumulate
                t = np.arange(16000) / 16000.0
                mic = 0.3 * np.sin(2 * np.pi * 440 * t) + 0.05 * np.random.randn(16000)
                mic_pcm = self._make_pcm16(mic)
                for i in range(0, len(mic_pcm), 1600):
                    out = ec.process(mic_pcm[i:i+1600])
                    out_arr = np.frombuffer(out, dtype=np.int16).astype(np.float64) / 32768.0
                    if not np.all(np.isfinite(out_arr)):
                        errors.append(f"Non-finite output at chunk {i}")
            except Exception as exc:
                errors.append(f"Process error: {exc}")
        
        t1 = threading.Thread(target=feed_reference)
        t2 = threading.Thread(target=process_mic)
        t1.start()
        t2.start()
        t1.join()
        t2.join()
        
        self.assertEqual(len(errors), 0, f"Concurrent errors: {errors}")
        self.assertTrue(np.all(np.isfinite(ec._filter)))


if __name__ == "__main__":
    unittest.main(verbosity=2)