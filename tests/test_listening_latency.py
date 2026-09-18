"""
tests/test_listening_latency.py

Bug 6 regression tests — listening promptness through the REAL capture
chain (DuplexVoiceSession.process_chunk -> echo canceller -> FFT
suppressor -> SileroVAD/WebRTC fallback VAD).

Runtime evidence (measured on this machine):
  * syllable-like speech onsets fire within ~0.5 s through the full chain,
    even right after a loud stationary background (the suppressor's speech
    gate + minimum tracking recover immediately);
  * the chain therefore cannot account for multi-second
    capture_start->speech_start delays — those come from genuine silence
    inside long idle windows (e.g. unexpected voice-prompt captures, now
    removed for plain "open Chrome") or upstream mic starvation.

No microphone, model download, or network is used (SileroVAD runs on its
WebRTC fallback via auto_load=False; the transcriber is a stub).
"""
from __future__ import annotations

import math
import struct
import threading
import time
import unittest

from voice.duplex import DuplexVoiceSession
from voice.microphone_processor import MicrophoneProcessor
from voice.silero_vad import SileroVAD

_SR = 16000
_CHUNK = 1024  # bytes = 512 samples = 32 ms
_MAX_ONSET_CHUNKS = 32  # ~1 s; measured onset is ~13 chunks


def _burst_chunk(phase: list, amp: float = 0.05) -> bytes:
    """Syllable-like voiced bursts: 150 ms voiced / 100 ms gap, wandering
    pitch. This is what the VAD + suppressor are designed for (a perfectly
    stationary tone is tracked as background noise by design)."""
    out = []
    for _ in range(_CHUNK // 2):
        t = phase[1] / _SR
        cyc = t % 0.25
        f0 = 110.0 + 40.0 * math.sin(phase[1] * 0.0001)
        p = phase[0]
        if cyc < 0.15:
            s = (math.sin(p) * 0.6 + math.sin(2 * p) * 0.3
                 + math.sin(3 * p) * 0.15) * amp
        else:
            s = 0.0
        out.append(int(max(-32767, min(32767, s * 32767))))
        phase[0] += 2 * math.pi * f0 / _SR
        phase[1] += 1
    return struct.pack("<%dh" % len(out), *out)


def _steady_chunk(phase: list, amp: float) -> bytes:
    out = []
    for _ in range(_CHUNK // 2):
        p = phase[0]
        s = (math.sin(p) * 0.6 + math.sin(2 * p) * 0.3
             + math.sin(3 * p) * 0.15) * amp
        out.append(int(max(-32767, min(32767, s * 32767))))
        phase[0] += 2 * math.pi * 130 / _SR
    return struct.pack("<%dh" % len(out), *out)


class _StubTranscriber:
    def begin(self) -> None:
        pass

    def push(self, data: bytes) -> str:
        return ""

    def partial_text(self) -> str:
        return ""

    def finalize(self, voiced_seconds=None):
        return None

    def discard(self) -> None:
        pass


def _session():
    vad = SileroVAD(auto_load=False)
    assert vad.backend == "webrtc"
    return DuplexVoiceSession(capture_vad=vad, transcriber=_StubTranscriber()), vad


def _onset_within(session, vad, feed, limit: int = _MAX_ONSET_CHUNKS) -> int | None:
    for i in range(1, limit + 1):
        feed()
        if vad.triggered:
            return i
    return None


class TestListeningLatency(unittest.TestCase):
    def test_speech_onset_is_prompt_through_full_chain(self) -> None:
        """Speech-like onsets are detected in ~0.5 s, not seconds."""
        session, vad = _session()
        session._in_capture = True
        phase = [0.0, 0]
        fired = _onset_within(session, vad, lambda: session.process_chunk(_burst_chunk(phase)))
        self.assertIsNotNone(
            fired,
            f"VAD onset did not fire within {_MAX_ONSET_CHUNKS} chunks (~1 s) "
            "of speech-like audio — speech detection is delayed in the chain",
        )

    def test_onset_prompt_despite_loud_background_history(self) -> None:
        """A loud stationary background must not stall the next onset."""
        session, vad = _session()
        session._in_capture = True
        phase = [0.0, 0]
        for _ in range(60):
            session.process_chunk(_steady_chunk(phase, amp=0.30))
        self.assertGreater(session._noise_suppressor.noise_floor, 0.05)
        vad.reset()
        fired = _onset_within(session, vad, lambda: session.process_chunk(_burst_chunk(phase)))
        self.assertIsNotNone(
            fired,
            "speech onset stalled after loud background — "
            "capture would sit in idle-wait for seconds",
        )

    def test_stationary_background_is_suppressed_not_transcribed(self) -> None:
        """Stationary loud backgrounds are attenuated (music-suppression
        purpose); the suppressor must keep doing this."""
        import audioop

        from voice.noise_suppressor import NoiseSuppressor
        ns = NoiseSuppressor()
        phase = [0.0, 0]
        for _ in range(30):
            ns.process(_steady_chunk(phase, amp=0.20))
        out = ns.process(_steady_chunk(phase, amp=0.20))
        out_rms = audioop.rms(out, 2) / 32768.0 if out else 0.0
        self.assertLess(
            out_rms, 0.10,
            f"stationary background not suppressed (out rms={out_rms:.4f}); "
            "background audio would leak into STT",
        )

    def test_processor_does_not_gate_conversational_speech(self) -> None:
        """Calibrated front-end passes conversational-level bursts."""
        import audioop

        proc = MicrophoneProcessor(sample_rate=_SR, calibration_duration=0.0)
        proc.start()
        phase = [0.0, 0]
        gated = 0
        total = 20
        for _ in range(total):
            out = proc.process_chunk(_burst_chunk(phase, amp=0.05))
            if audioop.rms(out, 2) == 0:
                gated += 1
        self.assertLess(gated, total // 2, "noise gate is zeroing conversational speech")

    def test_quiet_capture_returns_without_hanging(self) -> None:
        """Silence returns no_speech at the idle timeout (never hangs)."""
        session, _vad = _session()
        stop = threading.Event()

        def feed_quiet():
            # Deterministic low-level dither, well below speech energy.
            state = [12345]
            while not stop.is_set():
                out = []
                for _ in range(_CHUNK // 2):
                    state[0] = (1103515245 * state[0] + 12345) & 0x7FFFFFFF
                    out.append(int((state[0] / 0x7FFFFFFF - 0.5) * 2 * 300))
                session.process_chunk(struct.pack("<%dh" % len(out), *out))

        feeder = threading.Thread(target=feed_quiet, daemon=True)
        feeder.start()
        try:
            started = time.monotonic()
            result = session.capture_command(timeout=1.0)
            elapsed = time.monotonic() - started
        finally:
            stop.set()
            feeder.join(timeout=2.0)
        self.assertFalse(result.success)
        self.assertEqual(result.reason, "no_speech")
        self.assertLess(elapsed, 3.0, "idle wait overran its timeout")


if __name__ == "__main__":
    unittest.main()
