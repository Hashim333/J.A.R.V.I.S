# JARVIS — Repair Report

Record of the defects found and fixed in this pass, with the evidence that each
fix works. Every change is in the repository; nothing here is a proposal.

---

## 1. Result

| | Baseline | Final |
|---|---|---|
| Test suite | **23 failed**, 778 passed, 14 subtests passed | **811 passed**, 0 failed, 14 subtests passed |
| Suite wall time | 685 s (two 30 s playback stalls + one hang) | 172 s |
| Interpreter faults | `CO_E_NOTINITIALIZED` (0x800401f0) thread crash | none |
| Application boot | watchdog false alarms every 20 s | none over a 4-minute live run |

Baseline log: `logs/pytest_full.txt`. Final log: `logs/pytest_final2.txt`
(811 = the original 807 plus 4 regression tests added for the fix in §4).

The 23 failures were **not** one bug. They were four groups:

1. real native-interop faults (window-handle truncation, unbalanced COM),
2. real pipeline/logic faults (recent files never listed; a dead cancellation
   guard; a 0-byte "success" reported as OK; a swallowed stream error),
3. stale test scaffolding that no longer matched production APIs, and
4. two live-only watchdog faults found by running the app — a false alarm
   during stable listening, and a healthy long utterance reported to the user
   as `ERROR [Backend Stalled]` (both in §4).

---

## 2. Native interop — Win32 and COM

Untyped `ctypes` calls marshal `HWND` as a 32-bit `int`. On 64-bit Windows that
truncates the handle, and the truncated value is then passed back to the OS as a
pointer — a wild read. The same window enumeration was copy-pasted into two
collectors, and COM was initialised and uninitialised around every single
lookup. A `CO_E_NOTINITIALIZED` fault surfaced on a worker thread during a full
suite run, which is the failure mode this class of bug produces.

**`world_model/collectors/win32_windows.py` (new)** — one typed home for user32
window primitives: `_get_user32()` with explicit `argtypes`/`restype`,
`iter_visible_windows()`, `foreground_pid()`, `window_pid(hwnd)`,
`window_title(hwnd)`, `window_title_for_pid(pid)`. The enumeration callback is
declared as `WINFUNCTYPE(BOOL, HWND, LPARAM)`.

**`world_model/collectors/win32_shell.py` (new)** — COM and shell primitives:
`recent_items_folder()` (typed `SHGetFolderPathW`), `explorer_folder_for_pid(pid)`,
`resolve_shortcut(path)`. COM is initialised **once per thread** and the
`Shell.Application` / `WScript.Shell` dispatches are cached per thread, replacing
per-lookup initialise/uninitialise churn.

**`world_model/collectors/system.py`** — the clipboard read moved to a
module-level `read_clipboard_text()` carrying full `argtypes`/`restypes` and
`wintypes.HGLOBAL`.

**`world_model/collectors/media.py`** — volume now uses the same `pycaw` /
`comtypes` path the project already uses in `automation/apps.py`, with a
documented default when unavailable; window enumeration rewired onto
`win32_windows`; its local `_get_foreground_pid` deleted. Fixed a media-player
name that could never match because the list was compared case-sensitively
(`" iTunes.exe"` → `"itunes.exe"`).

**`world_model/collectors/files.py`** — rewired onto `win32_windows` and
`win32_shell`; local duplicate helpers deleted. Two functional bugs fixed:

* `_get_recent_files()` called `sorted(recent_dir, key=os.path.getmtime)` on the
  **path string**. Python iterated the characters and called `getmtime()` on
  `'C'`, `':'`, `'\'`, … so it raised on the first element and the method always
  returned its empty cache. **Recent files were never reported at all.** It now
  lists the directory, filters `.lnk`, sorts by a safe mtime accessor, and
  resolves each shortcut through the cached COM dispatch.
* the terminal-name tuple mixed cases (`"windowsTerminal.exe"`) while the name it
  was compared against had already been case-folded, so Windows Terminal could
  never be recognised as a terminal. The set is now uniformly lower-case.

**Verified on this machine** (real, not mocked):

* `read_clipboard_text()` returned 9,374 characters of real clipboard content.
* `iter_visible_windows()` returned 10 visible windows with correct Unicode titles.
* `recent_items_folder()` resolved to
  `C:\Users\muham\AppData\Roaming\Microsoft\Windows\Recent`.
* `FilesCollector` now returns real recent files where it previously returned
  `[]`; `SystemCollector` returns live CPU / RAM / GPU / battery / network.

---

## 3. Voice playback and TTS provider

**`voice/player.py`** — the pump iterated its chunk source with no `try/except`.
A source raising mid-stream (`OSError("socket died")`) killed the pump thread, no
end-of-stream sentinel was sent, and the worker reported success with
`last_play_bytes == 0` and `last_play_error is None` — a silent truncation
presented as a completed utterance. The pump now captures the exception and the
worker reports it in `last_play_error`.

**`voice/manager.py`** — two lifecycle faults:

* `cancel_all()` claimed to be generation-safe, but read the generation and
  compared it against **itself** under the same lock, so the guard could never
  fire: the documented protection did not exist. `cancel_all()` now takes an
  optional `expected_generation`, and a `generation` property exposes the counter
  callers capture when they enqueue. Called with no argument the behaviour is
  unchanged (unconditional), so every existing call site keeps working.
* `stop()` published `ERROR / "Interrupted"` whenever speech was interrupted.
  A barge-in or a cancellation is normal, not a failure, and this painted an
  error state over a user who simply spoke over JARVIS. The emit is removed;
  conversation state is owned by `services/conversation_owner`.
* `datetime.utcnow()` (deprecated in 3.12+) replaced with a timezone-aware call.

`_playback_consumed()` already refused to call a 0-byte stream a success; the
0-byte case could never be *detected* while the worker reported no error, which
is what the `player.py` fix restores.

**`voice/elevenlabs_provider.py`** — the HTTP status was checked *after* the
early return for a successful stream, so a 401/429 that returned a JSON body was
routed into the PCM player instead of being evaluated as a quota/auth failure.
Status handling now precedes any streaming, and the unreachable
`status != 200` retry branch inside the audio loop is gone.

---

## 4. Conversation lifecycle

**`services/conversation_owner.py` — direct listening.** With the wake word
disabled the microphone is open permanently, so low-confidence fragments arrive
from ordinary background noise. The code spoke *"Sorry sir, could you repeat
that?"* and then blocked on a 10-second TTS wait for each one — JARVIS talking to
itself and delaying every subsequent capture. The low-confidence path in direct
listening is now subtitle-only ("Ready when you are."), exactly like the existing
no-speech path. Confirmed live in the application log:

```
WAKE_CAPTURE low confidence (0.155) -> direct listening, subtitle only
```

**`services/conversation_owner.py` — state-change watchdog false positive.**
The watchdog fires when the conversation state has not changed for 20 s, and its
own docstring says a LISTENING state is only a stall when there is *no active
capture*. Direct listening is deliberately pinned to LISTENING
(`DIRECT-LISTEN-STABLE`), so the state never changed, `_last_state_change` grew
without bound, and the watchdog fired **CRITICAL, dumped every thread stack, and
restarted the capture every 20 seconds during completely normal idle listening**
— destroying its own signal value and perturbing the pipeline it was meant to
protect. Two changes:

* a LISTENING state with an armed capture is treated as progress
  (`_capture_is_active()`, using the `is_capture_active()` accessor the duplex
  session already exposes for exactly this question), and
* `_note_activity()` resets the stall clock after every completed capture,
  because direct listening cycles captures inside its own inner loop and the
  outer loop's state-change check is never reached while listening continues.

Genuine stalls still recover: with no capture armed and the clock past the limit,
the watchdog still dumps stacks and attempts recovery.

**`services/conversation_owner.py` — the loop heartbeat during a long capture.**
Found on the live re-run, and a more serious symptom than the alarm above:

```
23:59:37 CAPTURE MAX UTTERANCE reached after 15.0s — finalizing
23:59:37 faster_whisper: Processing audio (11.28 s)   <- pass 1
23:59:41 faster_whisper: Processing audio (11.28 s)   <- RETRY pass
23:59:48 faster_whisper: Processing audio (11.28 s)   <- RETRY2 pass
23:59:49 Transcriber finalize exceeded 12s — aborting capture
00:00:23 [ERROR] Watchdog[backend_loop] STALL detected — 63.2s since last heartbeat
00:00:23 UI STATE: LISTENING -> ERROR [Backend Stalled] | Core Offline
```

A single utterance — a 15 s max-utterance capture followed by three full
transcription passes — legitimately occupies the conversation thread for over a
minute. The loop is *inside* `capture_command` for that whole time and therefore
cannot kick its own `backend_loop` (60 s) or `state_change` watchdogs, so a
perfectly healthy utterance published `ERROR [Backend Stalled] | Core Offline`
to the user.

`_capture_with_heartbeat()` now runs the capture while a small daemon thread
feeds the `backend_loop` / `conversation` watchdogs and the stall clock every
second, and both capture call sites go through it. A capture is bounded by its
own hard limits (max utterance, finalize deadline), so an in-flight capture is
progress; a loop wedged anywhere else still trips the watchdog.

Verified:

* unit-level regression tests in `tests/test_state_recovery.py`
  (`TestWatchdogQuietDuringCapture`): an armed capture is not a stall and does
  not trigger recovery, a LISTENING state with nothing armed still recovers,
  `_note_activity()` resets the clock, and a capture that outlives the call
  keeps the heartbeat firing;
* live, ~4 minutes with captures cycling `gen=1` … `gen=23`: **no** `STALL
  detected`, no thread-stack dump, no `ERROR` state and no `Core Offline` —
  where the previous run produced both alarms (`logs/run_verify_final2.txt`).
  This also closed the residual boot-window alarm, because the heartbeat starts
  as soon as the first capture call begins.

---

## 5. Reasoning and speech intelligence

**`thinking/speech_intelligence.py`.** `_correct_medium()` step 2 called
`get_exact_match()`, which correctly returns the canonical installed-app name
(case-insensitively), and then **discarded** it and returned `EXECUTE` with the
raw text. So a case-insensitive exact hit never normalised the name. Step 2 now
returns the canonical name via `CORRECT`. The anti-fuzzy-correction guarantee is
preserved: only exact (case-insensitive) matches are rewritten, so "Notepad" is
still never turned into "Notepad++". A repository-wide search confirmed nothing
outside the test's own method name depended on the discarded value.

The `test_reasoning_pipeline` failures were **not** product defects. The
deterministic-command step deliberately runs before the reasoner step (a
documented latency decision), and the phrases the tests used were all resolved
deterministically — so the reasoner was never consulted. The tests now use
phrases that genuinely reach the reasoner, and their world-state fixture reflects
the navigation the retry performs. Verification reading the real `active_url` and
rejecting navigation that never happened is correct behaviour, so the fixture was
corrected rather than the product.

---

## 6. Test scaffolding that had drifted

These files were repaired because they no longer matched production APIs — the
product was right. This distinction matters, so each is listed rather than
lumped in.

* **`tests/fake_bridge.py` (new)** — a bridge-faithful double recording
  `core_states`, `subtitles`, `current_tasks`, `errors`, `window_actions`. It is
  a plain class, not a `MagicMock` subclass: subclassing `MagicMock` recursed
  infinitely through `_get_child_mock`.
* **`tests/test_elevenlabs_quota.py`** — was patching
  `voice.elevenlabs_provider.urllib.request.urlopen`, a symbol that does not exist
  (the provider uses `requests`). Rewritten against `requests.Session.post`; it
  still asserts the FIX-QUOTA behaviour — 401/429 fail once with no retry and set
  a sticky `_quota_blocked`, 503 retries twice, and an error body is never handed
  to the player.
* **`tests/test_duplex.py`** — the barge-in test lacked the preconditions the
  guard legitimately requires (a locked delay line and positive ERLE). Both are
  real anti-self-interrupt protections reachable in production, so the harness was
  given a `ReadyEchoCanceller` rather than the guard being weakened.
* **`tests/test_tts_playback_lifetime.py`** — `FakeResponse` gained
  `iter_content(chunk_size=...)` to match the streaming interface the player
  consumes.
* **`tests/test_direct_listening.py`, `test_no_auto_shutdown.py`,
  `test_runtime_persistence.py`** — switched to `FakeBridge`; they previously
  asserted against `set_backend_heartbeat`, which exists only in tests and never
  in `ui/bridge.py` or any production path.

---

## 7. Verification performed

* Full suite: **811 passed, 0 failed, 14 subtests passed in 171 s** —
  `logs/pytest_final2.txt`, run after every fix in this report.
* Focused suites, all green: `test_elevenlabs_quota` (7),
  `test_reasoning_pipeline` (11), `test_duplex` (35),
  `test_speech_intelligence` (26), `test_tts_playback_lifetime` (17), and the
  manager/conversation group (48).
* Collectors exercised against the live machine (see §2).
* Application booted with `python run.py`: services, world model, awareness,
  voice and GUI all started; the direct-listening fix is visible in the log; no
  `ERROR`/`CRITICAL`/traceback and no `CO_E_NOTINITIALIZED` fault.
* Live run held for ~4 minutes with captures cycling continuously: silent
  watchdogs, a stable LISTENING UI state, and no error state
  (`logs/run_verify_final2.txt`).

---

## 8. Known limitations

Stated plainly rather than left implied:

* **`pycaw` is not installed** in this environment, so reading and setting the
  system volume falls back to the documented default and `automation/apps.py`
  reports volume control as unavailable. This is a dependency decision, not a
  code defect — the code degrades honestly instead of failing. Installing
  `pycaw` would enable real volume control with no further change.
* **The window between registering the watchdogs and the first capture call is
  not covered by the heartbeat** (microphone arming happens there). If that
  window ever exceeded the 20 s limit the state-change watchdog could fire once
  at boot; the live run showed no such alarm, and it cannot recur once captures
  start.
* **Transcription cost is the real latency driver.** Three Whisper passes over
  an 11 s utterance is ~35 s of work; the heartbeat now makes that invisible to
  the watchdogs, but it is still ~35 s before the user sees a response. That is
  a tuning question (retry budget / model size), not a correctness defect, and
  was left as-is.
* **The GUI was exercised through `run.py` startup and bridge state logging**,
  not by human interaction with every widget.
* Two files in the collectors package are longer than the project's own 150-line
  guidance (`files.py`, `media.py`) because each is a single cohesive collector;
  the shared native code has been extracted into `win32_windows`, `win32_shell`
  and the module-level clipboard helper.
