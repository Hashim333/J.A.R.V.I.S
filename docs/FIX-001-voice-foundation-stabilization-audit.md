# FIX-001 — Voice Foundation Stabilization: Audit Report

Scope: stabilize the existing voice conversation pipeline (wake word, STT
accuracy, VAD, conversation state machine, timeouts, echo). No new features,
no UI redesign, no automation changes.

---

## 1. Bugs found and fixed

### Bug 1 — Vosk wake check starved the microphone thread during capture
`voice/duplex.py` (`DuplexVoiceSession.process_chunk`)

Every audio chunk was fed to the wake detector whenever wake detection was
armed. The detector's VAD runs a full **Vosk decode** (`LocalWakeWordDetector
.contains_wake_word`) synchronously on the microphone thread for *every*
speech segment. Because wake stays armed while a `capture_command` is running,
a multi-hundred-ms Vosk decode could run mid-command and clip the very audio
being recorded — a prime suspect for the random "I didn't understand" /
"could you repeat that" responses.

**Fix:** wake detection is suspended while `_in_capture` is True. Barge-in
("jarvis" spoken while JARVIS is talking) is handled by the barge-in VAD, not
the wake detector, so nothing is lost. Verified the wake detector is re-armed
on every return to Idle (`ConversationManager._rearm_wake` →
`WakeWordService.reset_for_wake` → `duplex.reset_wake()` +
`start_wake_detection()`), so the suspension is strictly scoped to capture.

### Bug 2 — Instant barge-in never fired (VAD reset loop)
`voice/duplex.py` (`arm_barge_in`)

`ConversationOwner` re-arms barge-in on every backend-loop iteration while
TTS is speaking (`start_barge_in()` ≈ every 50 ms). `arm_barge_in()` reset the
barge-in VAD on every call, so the onset accumulator (2 of 3 frames ≈ 64 ms of
speech) could never reach the majority threshold before the next reset. Net
effect: instant echo-cancelled barge-in was effectively disabled in
ACTIVE_CONVERSATION/WAITING_CONFIRMATION — the main barge-in path.

**Fix:** `arm_barge_in()` is now idempotent — the VAD is reset only on the
disarmed→armed transition, so the ~50 ms re-arm cadence no longer clears the
onset accumulator.

### Bug 3 — Stale documentation of the active STT path
`voice/__init__.py`

The module docstring claimed the active path was `voice.duplex` +
`voice.streaming_stt` (Vosk). The live capture STT engine is
`voice.whisper_stt.WhisperRecognizer` (Faster-Whisper); `streaming_stt` is
retained only as the shared `FinalTranscript` result type and a
tested-but-inactive fallback. Corrected the docstring.

---

## 2. Single-owner architecture — verified

| Concern | Single owner | Where |
|---|---|---|
| Microphone | `MicrophoneStream` (opened once, guarded by `audio_lock`) | `run.py:127` |
| Mic consumer | `duplex_session.process_chunk` | `run.py:250` |
| Wake detector | `WakeWordDetector` (lazy, inside duplex, on echo-cancelled audio) | `duplex.py:368` |
| Capture / barge-in VAD | two `SileroVAD` instances inside duplex (WebRTC fallback) | `duplex.py:190/198` |
| STT | `WhisperRecognizer` (Faster-Whisper) | `duplex.py:181` |
| Conversation owner | `ConversationOwner` (the single loop) | `run.py:326` |
| State machine | `ConversationManager` (one, driven only by the owner) | `run.py:239` |
| TTS | `VoiceEngine` + `VoiceManager` (never changes conversation state) | `run.py:135` |

Wake-word implementations compose rather than conflict: `WakeWordDetector`
(`voice/wakeword.py`) uses VAD for boundaries + `LocalWakeWordDetector`
(Vosk, offline) for the "jarvis" check; `PorcupineWakeWord` is off by default
(no Picovoice key) and falls back cleanly. `streaming_stt.StreamingTranscriber`
and `microphone_stream.capture_utterance` are legacy/inactive but tested; the
`VoiceEngine` legacy consumer-swap barge-in is guarded by the duplex session's
presence.

---

## 3. Timeouts and state machine — reviewed

- Conversation activity timeout: 30 s (`run.py`), confirmation: 15 s.
- Capture: two-phase — Phase A idle wait up to 30 s, Phase B utterance up to a
  hard 30 s cap (`_MAX_CAPTURE_SECONDS`); the idle timer starts on speech, not
  on wake.
- Watchdogs: backend loop 60 s, conversation 90 s; recovery cancels the hung
  task, `cancel_capture()`, unmutes, forces Idle.
- Wake loop: "no speech" prompts stay listening up to 5 rounds then return to
  wake; empty / low-confidence / rejected recognition is a repeat prompt, never
  NO_COMMAND.
- Task cleanup on supersede: cancels brain, TTS (`cancel_all` + `stop_barge_in`),
  wake, and mic.
- Event queue is bounded (64) with drop-oldest; capture drains stale events at
  entry. No deadlocks found; the one benign race (SileroVAD background backend
  swap vs. a stale `_delegate` read) is caught by per-tap try/except in duplex.

---

## 4. Recognition improvements — verified in place

- Whisper (Faster-Whisper, int8 CPU) batch decode with `beam_size=5`,
  `temperature=0`, word timestamps.
- Confidence gate: overall ≥ 0.5, single-word ≥ 0.6, min 2 chars; low-confidence
  retry pass with altered settings; per-word/per-sentence confidence carried to
  the Speech Intelligence Layer.
- Capture/barge-in VAD = Silero (ONNX) with WebRTC fallback; pause-tolerant
  hangover (2 s), majority-onset (fast first word), adaptive noise floor.
- Front end: DC removal, 80 Hz high-pass, AGC (0.15), adaptive noise gate,
  speech normalization.
- Echo cancellation via playback reference (`player.on_chunk_written` →
  `feed_playback_reference`), replacing mic-mute, so JARVIS cannot wake, trigger
  barge-in, or create phantom commands.

---

## 5. Dead code / duplicates — documented (not removed)

- `voice/interruption.py` — 0-byte stub, nothing imports it.
- `voice/convflow/` — a parallel conversation framework explicitly "NOT wired
  into run.py"; referenced only by its own tests. Kept as documented dead code.
- `voice/streaming_stt.StreamingTranscriber` — inactive Vosk engine; kept as the
  shared result type and tested fallback.
- `voice/porcupine_wake.py` — optional accelerator; off without a Picovoice key.

---

## 6. Files modified (FIX-001)

- `voice/duplex.py` — Bug 1 (wake suspension during capture), Bug 2
  (idempotent barge-in arming).
- `voice/__init__.py` — Bug 3 (docstring).
- `tests/test_duplex.py` — +2 regression tests
  (`test_wake_not_fed_detector_while_capturing`,
  `test_arm_barge_in_is_idempotent`).

## 7. Test status

- `tests/` — **615 tests** (613 baseline + 2 new). Same pre-existing
  `failures=9, errors=2`: 2 ImportErrors (`test_duplicate_command_prevention`,
  `test_voice_milestone`), 6 `test_reasoning_pipeline`, 3
  `test_response_quality`. **No regressions.**
- `dev_tests/` — 932 tests with a pre-existing `failures=31, errors=65` set
  (stale pre-redesign `WakeWordService`/consumer tests, plus import/env issues
  in unrelated modules). None exercise the changed code paths;
  `test_microphone_processor.py` passes 22/22.

Stabilization complete — no further work per task scope.
