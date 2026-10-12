# JARVIS — Project Status

Snapshot of the system as it stands after this repair pass. For the defect list
and evidence, see `REPAIR_REPORT.md`.

---

## 1. Health

| Check | Status |
|---|---|
| Full test suite | **811 passed, 0 failed, 14 subtests passed** (~3 min) |
| Application boot (`python run.py`) | Services, world model, awareness, voice and GUI all start; direct listening active |
| Live run | ~4 minutes continuous, captures cycling, no watchdog alarms and no error state |
| Collectors (live) | Clipboard, windows, recent files, system metrics, downloads all returning real data |
| Interpreter faults | None (no `CO_E_NOTINITIALIZED` / access violations) |

Logs: `logs/pytest_final2.txt` (suite), `logs/run_verify_final2.txt` (live run).

---

## 2. How to run

```
.venv\Scripts\activate
python run.py
```

Configuration lives in `config/settings.py` (and its environment overrides).
`WAKE_WORD_ENABLED` selects the interaction model:

* **`false` — direct listening.** The microphone stays open; the owner enters
  the capture path immediately and the UI holds one stable listening state.
  Low-confidence and no-speech results are subtitle-only, never spoken.
* **`true` — wake-gated.** The owner waits for the wake phrase before capturing.

Run the suite with:

```
python -m pytest tests -q
```

---

## 3. Component map

| Area | Path | Responsibility |
|---|---|---|
| Bootstrap | `run.py` | Builds every component, starts the owner on a background thread, handles shutdown |
| Conversation owner | `services/conversation_owner.py` | The single owner of conversation state: capture, command dispatch, TTS waits, watchdogs, mic recovery |
| State machine | `services/conversation_manager.py` | `ConversationManager` / `ConversationState` — every transition flows through here |
| UI bridge | `ui/bridge.py` | Publishes `coreState`, subtitles, task labels to the GUI |
| Capture / duplex | `voice/duplex.py` | `capture_command`, VAD, barge-in arming and onset detection, STT orchestration |
| Echo cancellation | `voice/echo_canceller.py` | Delay-locked AEC; `delay_locked` / `erle_db` gate barge-in |
| Speech recognition | `voice/whisper_stt.py` | faster-whisper (small, en) with confidence and retry passes |
| Transcription gate | `thinking/speech_intelligence.py` | Confidence bands → EXECUTE / CORRECT / ASK / REFUSE |
| TTS coordination | `voice/manager.py` | Speech queue, provider fallback, activity bookkeeping (`is_busy`) |
| TTS providers | `voice/elevenlabs_provider.py`, `voice/piper_provider.py`, `voice/system_provider.py` | Cloud, local, and OS voices |
| Audio playback | `voice/player.py` | Streaming jitter pump, byte accounting, play-error reporting |
| Reasoning | `thinking/pipeline.py` | `IntelligentPlanner`: deterministic commands, reasoner, execution, verification, auto-retry |
| LLM | `brain/llm.py`, `brain/llm_providers/` | Gemini (primary), Ollama (local fallback), rule pipeline |
| World model | `world_model/world_model.py` + `world_model/collectors/` | Background-polled machine state |
| Native interop | `world_model/collectors/win32_windows.py`, `win32_shell.py` | Typed user32 / COM helpers — the only place raw Win32 marshalling lives |
| Automation | `automation/apps.py`, `automation/application_registry.py` | App launch/close, volume, the app registry |
| Watchdogs | `monitoring/watchdog.py` + the owner's callbacks | Liveness detection for the loop, conversation and state changes |
| Tasks | `tasks/task_manager.py` | Task lifecycle, cancellation, timeouts, cleanups |

---

## 4. Behaviour verified live

From `logs/run_startup.txt` and `logs/run_verify_final2.txt`:

* Boot completes and the owner starts listening; captures cycle continuously.
* Direct listening handles background noise correctly — a low-confidence
  fragment logs `WAKE_CAPTURE low confidence ... direct listening, subtitle
  only` and returns to listening without speaking or stalling.
* LLM health is checked once at startup (Gemini reachable); the app never
  claims reasoning it does not have.
* World-model collectors return live CPU / RAM / GPU / battery / network /
  clipboard / windows / recent files.

---

## 5. Testing conventions in this repo

* `unittest` style, one file per area under `tests/`.
* Owner-level tests build a `ConversationOwner` with `_make_owner(...)`
  (`tests/test_state_recovery.py`) or `FakeBridge` (`tests/fake_bridge.py`).
* `FakeBridge` is a plain class, **not** a `MagicMock` subclass — subclassing
  `MagicMock` recurses through `_get_child_mock`.
* Watchdog, capture and playback behaviour is covered by
  `test_state_recovery.py`, `test_no_auto_shutdown.py`,
  `test_tts_playback_lifetime.py` and `test_duplex.py`.

---

## 6. Known gaps and dependencies

* **`pycaw` is not installed.** Volume read/set falls back to the documented
  default and `automation/apps.py` reports volume control as unavailable.
  Installing `pycaw` enables it with no code change.
* **Piper voice model** is optional; when the model file is absent the manager
  skips straight to the system voice.
* **The window between registering the watchdogs and the first capture call is
  not covered by the heartbeat** (microphone arming happens inside it). A boot
  alarm is possible only if that window exceeds the 20 s limit; the live run
  showed none, and it cannot recur once captures start.
* **Transcription latency is the dominant cost.** A long utterance plus the
  Whisper retry passes can exceed 30 s before a reply is ready. The watchdogs no
  longer misreport it (see `REPAIR_REPORT.md` §4), but tuning the retry budget or
  model size would reduce the real wait.
* **GUI coverage is startup-level.** The interface is exercised through
  `run.py` and bridge state logging rather than automated widget interaction.
* **`voice/duplex.py` and `thinking/pipeline.py` are large.** Both are
  central, single-responsibility modules with long, well-documented flows;
  splitting them further is a refactor, not a repair, and was deliberately not
  attempted here.
* **`world_model/collectors/files.py` and `media.py`** exceed the 150-line
  guidance as single cohesive collectors; their shared native code now lives in
  `win32_windows.py` / `win32_shell.py`.
