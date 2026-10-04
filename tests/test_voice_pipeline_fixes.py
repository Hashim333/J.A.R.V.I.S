"""Focused voice-pipeline tests (no mic/TTS/network required).

Covers: clean speech, silence, noise, short command, normal sentence,
Indian-English phrasing, post-TTS speech, barge-in, empty result,
low-confidence, hallucination, consecutive turns, VAD start/end,
single mic consumer, Ollama-unavailable fallback.
"""
import struct

from voice import whisper_stt
from voice.duplex import DuplexVoiceSession
from voice.microphone_processor import MicrophoneProcessor
from voice.silero_vad import SileroVAD
from voice.transcript_quality import is_pathological, known_app_command
from thinking.speech_intelligence import (
    SpeechIntelligenceLayer, SpeechTranscript, SpeechAction,
    InstalledAppMatcher,
)
from voice.streaming_stt import FinalTranscript


def _pcm(seconds, amp=8000):
    n = int(16000 * seconds)
    return struct.pack("<%dh" % n, *([int(amp)] * n))


def _silence(seconds):
    n = int(16000 * seconds)
    return struct.pack("<%dh" % n, *([0] * n))


class _Seg:
    def __init__(self, text, avg=-0.3, no_speech=0.1, start=0.0, end=1.0):
        self.text = text
        self.avg_logprob = avg
        self.no_speech_prob = no_speech
        self.start = start
        self.end = end
        self.words = []


class _Model:
    def __init__(self, segs):
        self._segs = segs
        self.calls = 0

    def transcribe(self, audio, **kwargs):
        self.calls += 1
        return (list(self._segs), {})


def _rec(segs, **kw):
    return whisper_stt.WhisperRecognizer(
        sample_rate=16000, model_factory=lambda: _Model(segs),
        enable_partials=False, **kw,
    )


def _layer():
    return SpeechIntelligenceLayer(
        app_matcher=InstalledAppMatcher(apps=["Google Chrome"], scan_now=True),
    )


# 1. clean speech accepted
def test_clean_speech_accepted():
    r = _rec([_Seg("open chrome", avg=-0.1, no_speech=0.01, end=1.0)])
    r.begin()
    r.push(_pcm(1.0))
    f = r.finalize(voiced_seconds=1.0)
    assert f.accepted, f.rejected_reason


# 2. quiet silence fails fast without decode
def test_silence_fails_fast_no_decode():
    m = _Model([_Seg("hello")])
    r = whisper_stt.WhisperRecognizer(
        sample_rate=16000, model_factory=lambda: m, enable_partials=False,
    )
    r.begin()
    r.push(_silence(1.0))
    f = r.finalize(voiced_seconds=0.0)
    assert not f.accepted
    assert m.calls == 0


# 3. background noise (low rms) fails fast
def test_background_noise_fails_fast():
    m = _Model([_Seg("play music play music play music")])
    r = whisper_stt.WhisperRecognizer(
        sample_rate=16000, model_factory=lambda: m, enable_partials=False,
    )
    r.begin()
    r.push(_pcm(1.0, amp=20))
    f = r.finalize(voiced_seconds=0.1)
    assert not f.accepted
    assert m.calls == 0


# 4. short command preserved
def test_short_command_pause_next():
    assert known_app_command("pause")
    assert known_app_command("next")
    lyr = _layer()
    d = lyr.process(SpeechTranscript(text="pause", confidence=0.5, speech_seconds=0.5))
    assert d.action in (SpeechAction.EXECUTE, SpeechAction.CORRECT)


# 5. normal sentence accepted on evidence, not threshold
def test_normal_sentence_accepted():
    r = _rec([_Seg("can you hear me", avg=-0.9, no_speech=0.05, end=1.2)])
    r.begin()
    r.push(_pcm(1.2))
    f = r.finalize(voiced_seconds=1.2)
    assert f.accepted, (f.text, f.confidence, f.rejected_reason)


# 6. Indian-English phrasing: language pinned, prompt with common commands for better recognition
def test_indian_english_phrasing():
    seen = {}

    class M:
        def transcribe(self, audio, **kw):
            seen.update(kw)
            return ([_Seg("what time is it", avg=-0.4, no_speech=0.1, end=0.8)], {})

    r = whisper_stt.WhisperRecognizer(
        sample_rate=16000, model_factory=M, enable_partials=False,
    )
    r.begin()
    r.push(_pcm(0.8))
    f = r.finalize(voiced_seconds=0.8)
    assert seen.get("language") == "en"
    # Updated: initial_prompt now set with common commands for better proper noun recognition
    assert "Open YouTube" in seen.get("initial_prompt", "")
    assert seen.get("beam_size", 99) <= 3  # CPU-efficient decode
    assert f.accepted


# 7. speech after TTS: echo-cancelled path still captures (preroll kept)
def test_post_tts_capture_path():
    s = DuplexVoiceSession(sample_rate=16000)
    # Updated: onset_frames reduced from 5 to 3 for faster onset
    assert s._capture_vad.onset_frames >= 3


# 8. user interruption during TTS triggers barge-in, TTS residue does not
def test_barge_in_armed_and_gated():
    fired = []
    s = DuplexVoiceSession(sample_rate=16000, on_barge_in=lambda: fired.append(1))
    s.arm_barge_in()
    s._trigger_barge_in()
    assert fired == [1]
    assert s._barge_in_vad._min_speech_frames >= 6  # 200ms @32ms


# 9. empty Whisper result rejected, never executed
def test_empty_result_rejected():
    r = _rec([])
    r.begin()
    r.push(_pcm(0.5))
    f = r.finalize(voiced_seconds=0.5)
    assert not f.accepted and f.rejected_reason == "no speech recognized"


# 10. low-confidence conversational rescued; garbage refused
def test_low_confidence_policy():
    lyr = _layer()
    ok = lyr.process(SpeechTranscript(
        text="can you hear me", confidence=0.25, speech_seconds=1.0))
    assert ok.action == SpeechAction.EXECUTE
    bad = lyr.process(SpeechTranscript(
        text="zzz qqq", confidence=0.25, speech_seconds=1.0))
    assert bad.action == SpeechAction.REFUSE


# 11. hallucinated repetition rejected, no retry decode
def test_hallucination_rejected_no_retry():
    m = _Model([_Seg("play music " * 12, avg=-0.1, no_speech=0.01, end=2.0)])
    r = whisper_stt.WhisperRecognizer(
        sample_rate=16000, model_factory=lambda: m, enable_partials=False,
    )
    r.begin()
    r.push(_pcm(2.0))
    f = r.finalize(voiced_seconds=2.0)
    assert not f.accepted
    assert is_pathological(f.text)
    assert m.calls == 1  # pathological must not trigger a retry decode


# 12. consecutive turns: recognizer reusable via begin()
def test_consecutive_turns():
    r = _rec([_Seg("what time is it", avg=-0.2, no_speech=0.05, end=1.0)])
    for _ in range(3):
        r.begin()
        r.push(_pcm(1.0))
        f = r.finalize(voiced_seconds=1.0)
        assert f.accepted


# 13. VAD speech start/end fires, blips rejected by majority onset
def test_vad_start_end_and_onset_majority():
    assert SileroVAD._onset_required(5) >= 4  # majority of 5
    assert SileroVAD._onset_required(3) == 2
    events = []
    vad = SileroVAD(
        on_speech_started=lambda: events.append("start"),
        on_speech_ended=lambda: events.append("end"),
        model=object(),  # placeholder; drive state machine directly
        silence_hangover_ms=96.0, min_speech_ms=32.0,
    )
    # With injected model, backend is silero; feed majority onset
    for _ in range(5):
        vad._process_frame(True, 0.9)
    assert "start" in events


# 14. no competing mic consumers
def test_single_mic_consumer_guard():
    from voice.microphone_stream import MicrophoneStream

    class FakeSession:
        pass

    FakeSession.__name__ = "DuplexVoiceSession"
    import types
    ms = MicrophoneStream.__new__(MicrophoneStream)
    ms._consumer = types.MethodType(lambda self, c: None, FakeSession())
    # consumer owner type name check path: emulate bound method of duplex
    from voice.duplex import DuplexVoiceSession as D
    ms2 = MicrophoneStream.__new__(MicrophoneStream)
    d = D.__new__(D)
    ms2._consumer = d.process_chunk
    assert type(ms2._consumer.__self__).__name__ == "DuplexVoiceSession"
    # capture_utterance must refuse when duplex owns consumer
    import logging
    logging.disable(logging.CRITICAL)
    try:
        assert ms2.capture_utterance(timeout=0.01) is None
    finally:
        logging.disable(logging.NOTSET)


# 15. Ollama unavailable fallback is fast and honest
def test_ollama_unavailable_fallback():
    from brain.llm import LLM, OllamaError
    from brain.llm_providers import OllamaProvider
    import time
    # Exercise the legacy provider directly: the LLM dispatcher now
    # routes to Gemini when a key is configured, so poking legacy attrs
    # onto a bare LLM no longer selects the Ollama path.
    llm = OllamaProvider(
        endpoint="http://localhost:1/api/generate",
        model="x",
        timeout=30,
        connection_timeout=0.2,
    )
    t0 = time.monotonic()
    try:
        llm.ask("hello")
        assert False, "expected OllamaError"
    except OllamaError:
        pass
    dt1 = time.monotonic() - t0
    assert dt1 < 5.0
    t0 = time.monotonic()
    try:
        llm.ask("hello again")
        assert False
    except OllamaError as e:
        assert "retry" in str(e).lower() or "unavailable" in str(e).lower()
    assert (time.monotonic() - t0) < 1.0  # fail-fast, no second connection wait
    assert llm.is_available is False


# Soft-gate preserves onsets instead of zeroing
def test_soft_gate_preserves_onsets():
    p = MicrophoneProcessor(
        sample_rate=16000, sensitivity=1.0, agc_enabled=False,
        noise_gate_enabled=True, noise_gate_threshold=0.02,
        calibration_duration=0,
    )
    p._calibrated = True
    p._noise_floor = 0.0
    # Alternating +/-400: survives the 80 Hz high-pass (a flat DC would be
    # correctly removed), rms ~0.012 — below gate 0.02, above gate*0.5.
    n = int(16000 * 0.064)
    chunk = struct.pack("<%dh" % n, *[400 if i % 2 else -400 for i in range(n)])
    out = p.process_chunk(chunk)
    assert out != b"\x00" * len(chunk)


# Capture must reset the VAD before arming: the mic thread feeds the VAD
# without holding the session lock, so arm-then-reset lets one chunk slip
# through the stale ambient-primed onset window -> bogus SPEECH DETECTED
# ~60 ms after capture starts (observed in a quiet room, floor 0.003).
def test_capture_resets_vad_before_arming():
    import threading
    from voice.duplex import DuplexVoiceSession
    from voice.silero_vad import SileroVAD

    order = []
    vad = SileroVAD(auto_load=False)
    # Prime the onset window with ambient "speech" before capture starts.
    s = DuplexVoiceSession(
        sample_rate=16000, capture_vad=vad, transcriber=_StubTranscriber(),
    )
    orig_reset = vad.reset
    orig_drain = s._drain_events

    def reset():
        order.append("reset")
        orig_reset()

    def drain():
        order.append("drain")
        orig_drain()

    vad.reset = reset
    s._drain_events = drain

    stop = threading.Event()

    def feed_silence():
        while not stop.is_set():
            s.process_chunk(_silence(0.064))

    t = threading.Thread(target=feed_silence, daemon=True)
    t.start()
    try:
        res = s.capture_command(timeout=0.4)
    finally:
        stop.set()
        t.join(timeout=2.0)
    assert order[:2] == ["reset", "drain"]
    # Silence only: no instant false onset from the primed window.
    assert not res.success and res.reason == "no_speech"


class _StubTranscriber:
    def begin(self): pass
    def push(self, data): return ""
    def partial_text(self): return ""
    def finalize(self, voiced_seconds=None): return None
    def discard(self): pass
    def reset(self): pass


# Decode uses capped beam (latency)
def test_decode_beam_capped():
    seen = {}

    class M:
        def transcribe(self, audio, **kw):
            seen.update(kw)
            return ([_Seg("hello world", end=0.5)], {})

    r = whisper_stt.WhisperRecognizer(
        sample_rate=16000, model_factory=M, enable_partials=False, beam_size=5,
    )
    r.begin()
    r.push(_pcm(0.5))
    r.finalize(voiced_seconds=0.5)
    assert seen["beam_size"] <= 3
