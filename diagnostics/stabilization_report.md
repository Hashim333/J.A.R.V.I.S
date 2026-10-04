# JARVIS Runtime Instability Diagnostic Report

**Date:** 2026-08-01
**Method:** Instrumented production run (`JARVIS_DIAG=1`) via `tests/diag_harness.py` (steady 120s + 20 stress commands + 60s soak + timed shutdown). Full log: `diagnostics/run_log.txt` (901 lines). Analyzer: `tests/diag_analyze.py`.
**Scope:** Evidence only. No fixes applied.

---

## Confirmed Root Cause (shutdown hang)

**Problem:** Sending `exit` (via stdin, the same channel the text-input thread uses) does **not** stop JARVIS within 60s. The harness had to kill the process (`Process did not exit within 60s — killing`).

**Cause:** The `exit` command is a plain item on the **unbounded** `command_queue` (run.py:407), processed serially by the single backend thread. Each preceding text command causes the loop to enter `ACTIVE_CONVERSATION` (run.py:207 `enter_active_conversation`), and the next loop iteration then blocks **13–16s** in `listener_service.listen_for_command` (run.py:294) waiting for voice that never comes. Stress burst of 20 commands + soak left ~9–20 items queued; `exit` sits at the tail and is starved.

**Evidence (run_log.txt):**
- `command_queue` peak = **20** (unbounded pile-up during the 0.35s-spaced stress burst).
- 7× `listen_for_command` durations: **13.8s, 15.9s, 16.5s, 16.5s, 16.4s, 5.2s, 13.0s** — each on `Thread-11 (_backend_loop)`, each following a text-command ACTIVE transition.
- Last processed commands: `open reddit` 01:44:49 → `battery status` 01:45:18 → `open github` 01:45:19. `exit` was never dequeued; log ends with `command_queue=9` while stress commands still drain.
- Harness Phase 4 `exit` sent after 20 stress + 60s soak; process still alive 60s later.

**Fix direction:** Prioritise shutdown — check `shutdown_event` / `_shutdown_in_progress` at loop top (run.py:155) and break before draining remaining commands; or drain-and-skip commands once shutdown is requested. Bound the ACTIVE-listen wait when a queued command is pending (`command_queue.qsize() > 0` → skip voice listen).

---

## Findings by Reported Symptom

### 1. UI freezes / 2. Not Responding
- **Problem:** No UI freeze reproduced in this 4-minute window, but UIMonitor (the only freeze detector) is **not wired into production** — only into tests (`tests/test_ui_freeze.py`) and now diag mode (run.py).
- **Cause:** `ui/monitor.py` `UIMonitor` is imported only under `JARVIS_DIAG`. In production the UI can freeze silently.
- **Evidence:** `[UI MONITOR] Installed` appears only in this diag run. No `[UI BLOCKED]` / `[UI FREEZE]` lines. UI tick held at 1.0/s (the diag QTimer) — no stall detected.
- **File/Line:** run.py (diag install block, ~line 565); `ui/monitor.py:63` `install()`.
- **Fix:** Always install UIMonitor in production (cheap: 200ms QTimer + stack sampler).

### 3. Slow / hung shutdown — **CONFIRMED, CRITICAL**
- See **Root Cause** above.
- **File/Line:** run.py:155 (loop top), run.py:170 (`exit` dequeue), run.py:207, run.py:290–294 (voice listen), run.py:407 (unbounded queue).
- **Evidence:** peak queue 20; process not exited in 60s; no `ShutdownManager` phase lines ever logged (shutdown never started).

### 4. Window disappears / taskbar icon
- **Problem:** Not reproduced. Potential contributors identified (frameless QWindow + `showMaximized` + mode transitions).
- **Historical cause:** the previous window shell polled foreground windows and used a native window path. That implementation has been removed; the current `WindowManager` only shows and hides the placeholder window.
- **Evidence:** no log lines this run; static review only.
- **Fix direction:** Guard mode transitions to occur after a fullscreen app truly exits; verify `_ensure_taskbar_icon` re-applies after mode switches.

### 5. High RAM — **CONFIRMED (transient), not a steady leak**
- **Cause:** Startup spike from GPU/WMI init; steady-state stable.
- **Evidence:** RSS 878→1020MB in first ~6s (GPU/WMI init), then stable **629–670MB** for the rest; first→last delta −243MB (post-spike). No monotonic growth.
- **File/Line:** ui/system_monitor.py (GPU lazy init), world_model/collectors/system.py.
- **Fix:** none required for leak; consider deferring WMI GPU init (already background-threaded).

### 6. High CPU — **CONFIRMED**
- **Problem:** CPU sustained 44–98% (avg ~65%) even during soak with no input.
- **Cause:** Multiple background pollers: `SystemMonitor` 2s poll (ui/system_monitor.py), `WorldModel` collectors (applications 2s, browser 3s, system 5s, media 5s — world_model/collectors), `WindowManager` 3s Win32 poll, `MicrophoneStream` continuous capture + `audioop` VAD, `ui-stack-sampler` 500ms, diag sampler. WorldModel runs 5 collectors sequentially on one thread (world_model/world_model.py:89) but each does Win32/WMI/psutil scans.
- **Evidence:** SNAPSHOT cpu values (e.g., 71%, 75%, 78%, 83%, 98%).
- **Fix direction:** Increase poll intervals; make browser/media collectors opportunistic (skip if no browser running).

### 7. Event loop blocked — **CONFIRMED (backend), NOT UI**
- **Cause:** Backend loop is the serial choke point: 13–16s voice listens + up to **34.2s** `pipeline.process` (LLM) block command draining. UI event loop stayed responsive (tick 1.0/s).
- **Evidence:** `pipeline.process` max **34,234ms**, p95 29.6s; `brain.process` max 34,234ms; `listen_for_command` max 16.5s; `executor.execute` max 4.2s (fast — good).
- **File/Line:** run.py:200/251/326 (`brain.process` on backend thread); brain.py:94 (`ThreadPoolExecutor(max_workers=1)` + `future.result(timeout=120)`).

### 8. Deadlocks
- **Problem:** No deadlock observed.
- **Evidence:** No `Watchdog[...] STALL` lines; all watchdog heartbeats kicked normally.
- **File/Line:** monitoring/watchdog.py:106 `_on_stall` logs only (critical) — no recovery.
- **Fix:** (report) Watchdog stall currently only logs; consider auto-dump.

### 9. Infinite loops
- **Problem:** None observed. Retry loops are bounded (`max_retries=3` pipeline, `max_attempts=3` listener).
- **Evidence:** All `TASK END` records present with `status=OK`; no hangs inside a single function > 34s.

### 10. Thread termination / world-model never stopped — **CONFIRMED BUG**
- **Problem:** `WorldStateService.stop()` is **never called** on GUI shutdown.
- **Cause:** `run.py:539` registers `shutdown_manager.on("stop_world_state", world_state.stop)`, but `ShutdownManager.PHASES` (services/shutdown_manager.py:12–21) contains **no** `stop_world_state` phase → `on()` silently drops it (`if phase in self._hooks` guard). The `world-model` daemon thread keeps polling until process death.
- **Evidence:** No `WorldModel: stopped` line anywhere in run_log.txt; `world-model[17644]d` present in every snapshot. Code-confirmed via shutdown_manager.py:27–29.
- **File/Line:** run.py:539 (dead hook); services/shutdown_manager.py:12–21 (phase list), :27 (`on()` drops unknown phases silently).

### 11. Repeated signals / timers
- **Historical problem:** UI signal churn was not directly measured; static risk.
- **Cause:** `Bridge` clock timer 1s (ui/bridge.py:105), `WindowManager` poll 3s (ui/window_manager.py:81), `SystemMonitor` 2s (ui/system_monitor.py), `UIMonitor` 200ms. All are bounded, but `subtitleChanged`/`conversationHistoryChanged` emit per subtitle line.
- **Evidence:** No explosion observed. UI tick steady.

### 12. Blocking I/O on UI thread
- **Problem:** Confirmed **risk** in WindowManager; not reproduced.
- **Cause:** `ui/window_manager.py:120 _poll_foreground` runs `GetForegroundWindow`, `GetWindowTextLengthW`, `GetWindowTextW`, `GetWindowRect` synchronously on the UI thread every 3s. Normally <1ms, but a stuck/loading window or OS slowness can stall the UI thread.
- **File/Line:** ui/window_manager.py:120–163.
- **Fix:** Move polling to a background thread (use `Signal` to update mode).

### 13. UI rendering loops
- **Problem:** Not reproduced / not instrumented.
- **Cause:** The previous animated visual shell is no longer part of the active application.
- **Evidence:** none from this run.
- **Fix:** measure rendering after the replacement interface is introduced.

### 14. Memory leaks
- **Problem:** No leak in 4-minute window (RSS flat after spike).
- **Evidence:** RSS stable 629–670MB over ~200 snapshots; thread count stable 11–15.
- **Fix:** none confirmed; re-soak longer (≥1h) if desired.

### 15. Worker → UI touches
- **Problem:** Mostly safe (Qt auto-queued `@Slot`), one violation.
- **Cause:** `run.py` backend thread writes **properties directly**: `bridge.wakeActive = True/False` (run.py:221/227) instead of a queued `@Slot`. Bridge docstring explicitly forbids this (ui/bridge.py:19).
- **File/Line:** run.py:221, 227; ui/bridge.py:19 (rule), :189 (setter).
- **Fix:** Add `@Slot(bool)` `set_wake_active` and call it; never assign properties cross-thread.

### 16. Executor blocking speech
- **Problem:** Not reproduced this run; `executor.execute` was fast (max 4.2s, p95 1.4s).
- **Evidence:** `executor.execute` outliers < 4.2s.
- **File/Line:** executor/executor.py:45 (`execute`), :240 (`handler.run(step, voice_input=...)`).
- **Fix:** none required currently; note `voice_input` in run.py:437 calls `listener_service.listen_for_command()` (no timeout → 10s default) on the executor thread if a handler requests it — that is a blocking path to watch.

### 17. Browser waits
- **Problem:** Not reproduced (no browser automation in this workload beyond `open_website`/`search` which were fast).
- **Evidence:** `open github`/`search` completed ~0.9s. YouTube flow not exercised (would be slow: CDP + verification polling with timeouts).
- **File/Line:** automation/youtube.py, thinking/pipeline.py verification polling (timeouts up to 120s in brain.py).
- **Fix:** none confirmed; long verification loops are the risk under real browser automation.

### 18. STT/TTS latency & provider failure — **CONFIRMED**
- **Problem:** ElevenLabs returns **HTTP 401 Unauthorized** (invalid key) → every TTS attempt wastes 2 network round-trips (~672ms + ~375ms) then errors; `VoiceManager` falls back to system voice.
- **Evidence:** `ElevenLabs: request failed (attempt 1, 672 ms): HTTP Error 401` ×2 + `all 2 attempts failed: HTTP Error 401` at startup; later `VoiceManager: OK (5 chars, 0 ms): 'Done.'` (system voice active).
- **File/Line:** voice/elevenlabs_provider.py (retries), voice/manager.py:287 fallback.
- **Fix:** Validate API key at startup (`_load_provider`, voice/manager.py:177) before creating the provider; skip network provider if key invalid.

### 19. Wake word / barge-in
- **Problem:** Barge-in cannot fire during TTS playback.
- **Cause:** Echo prevention mutes the mic during playback (`run.py:431-432` `player.on_playback_started = microphone_stream.mute`), and `microphone_stream` discards chunks while muted (voice/microphone_stream.py:399 `if consumer is not None and not self._muted`). Barge-in VAD consumes the same stream → no audio during playback.
- **File/Line:** run.py:431-432; voice/microphone_stream.py:151-158, :399; voice/engine.py:165.
- **Fix:** Route playback-reference/echo-cancelled audio to the barge-in VAD, or keep VAD active while discarding only the loudspeaker path.

### 20. Watchdog timeout mismatch — **CONFIRMED RISK**
- **Problem:** `conversation` watchdog timeout 60s vs `brain.process` timeout 120s; conversation watchdog only kicked at loop top (run.py:157), not before/after `brain.process`. A legit 60–120s LLM/executor operation would trip a false `conversation` STALL (which only logs, but floods and masks real stalls).
- **Evidence:** constants run.py:46-47; `Watchdog[conversation]` started (timeout=60.0s). No false trip this run (max brain.process 34s < 60s).
- **File/Line:** run.py:46-47, :157, :199/:250/:325; monitoring/watchdog.py:70.
- **Fix:** Raise conversation watchdog to > brain timeout, or kick it inside `_run_with_timeout` while awaiting the future.

---

## Telemetry Summary (run_log.txt)

| Metric | Value |
|---|---|
| Steady-state RSS | 629–670 MB (startup spike to 1020 MB) |
| CPU during soak | 44–98% |
| Thread count | 11 steady; peak 15 (one `ThreadPoolExecutor-N_0` per brain.process) |
| command_queue peak | 20 |
| brain.process | 13 runs, max 34.2s, p95 29.7s |
| listen_for_command | 7 runs (log-outliers), max 16.5s |
| executor.execute | 11 runs, max 4.2s |
| planner.create_plan | 11 runs, ≤1ms |
| Watchdog STALLs | 0 |
| UI freezes | 0 |
| Crashes | 0 |
| `WorldModel: stopped` | **absent** (world-model thread never stopped) |
| Shutdown phase logs | **absent** (shutdown never started) |

---

## Priority Fix List — STATUS

**P0 fixes applied & verified (2026-08-01):**

- ✅ **1 — Shutdown hang (P0):** `_backend_loop` now breaks immediately when `shutdown_in_progress` is set (checked at loop top and after dequeue, run.py:161-164, ~180); `_text_input_loop` sets `_shutdown_in_progress` on `exit`/`quit`/EOF (run.py:540-546); ACTIVE-conversation branch skips voice-listen when commands are queued (run.py:286-289). Verified: harness run v3 exited 38.3s after `exit` (vs kill after 60s); `Shutdown completed in 7.5s`; all phases logged.
- ✅ **2 — World-model leak (P0):** added `stop_world_state` to `ShutdownManager.PHASES` (services/shutdown_manager.py:12-21); `ShutdownManager.on()` now logs a warning for unknown phases (shutdown_manager.py:27-31). Verified: `Shutdown phase stop_world_state completed in 5000ms` in run_log_v3.

**Remaining (not yet applied):**

1. **P1 — Barge-in:** Feed barge-in VAD echo-cancelled audio instead of muting it. (run.py:431; voice/microphone_stream.py:399)
2. **P1 — CPU:** Increase world-model collector intervals; skip browser/media collectors when no browser runs. (world_model/collectors/*)
3. **P1 — ElevenLabs 401:** Validate key at provider creation. (voice/manager.py:177)
4. **P2 — Cross-thread property write:** `bridge.wakeActive =` → queued `@Slot`. (run.py:221/227)
5. **P2 — UI-thread Win32 poll:** Move `WindowManager._poll_foreground` off the UI thread. (ui/window_manager.py:120)
6. **P2 — Watchdog mismatch:** conversation timeout > brain timeout. (run.py:47)
7. **P2 — Always-on UIMonitor:** install in production. (ui/monitor.py)
