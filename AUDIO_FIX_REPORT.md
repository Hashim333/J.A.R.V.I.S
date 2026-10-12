# Audio Glitch — Root Cause and Fix (revision 2)

Clear, continuous speech; every word audible; no "broken radio" effect.

The first fix removed real audio loss but the distortion persisted, so this
revision records the **actual remaining cause**: the TTS playback thread was
being blocked inside the echo canceller, which stalled the audio output
mid-utterance.

---

## 1. The cause that was still breaking the audio — lock contention with the echo canceller

`voice/echo_canceller.py` used **one lock for both sides of its work**:

```python
def set_reference(self, pcm16_chunk):      # called from the TTS AUDIO thread
    with self._lock:                       # ← same lock…
        self._ref.extend(...)

def process(self, mic_chunk):              # called from the CAPTURE thread
    with self._lock:                       # ← …held for the whole NLMS DSP
        return self._process_locked(mic_chunk)
```

`process` held that lock while doing heavy work — building an `(n × taps)`
reference matrix (1024 × 320 ≈ **2.6 MB per chunk**), `R @ filter`,
`np.einsum`, more full-matrix passes — and `_estimate_delay` additionally ran a
**1280-iteration loop** with ~2560 numpy calls per chunk, on every chunk while
the delay was unlocked.

The player calls `on_chunk_written` → `duplex.feed_playback_reference` →
`set_reference` **from inside its audio write loop**, once per 23 ms slice. So
the audio thread waited for the capture thread's DSP on every slice, while
JARVIS was speaking.

### Measured

Contention benchmark, capture thread looping `process` while the playback
thread calls `set_reference` (200 feeds):

| | before | after |
|---|---|---|
| `setref_median_ms` | 7.47 | **0.07** |
| `setref_p95_ms` | 42.62 | **0.20** |
| `setref_p99_ms` | 143.59 | **0.36** |
| `setref_max_ms` | **168.74** | **0.37** |
| `setref_total_ms` (200 feeds) | **2545.41** | **17.02** |
| `process_median_ms` | 2.47 | **0.23** |

**The audio thread was blocked for up to 169 ms per call and 2.5 seconds in
total**, which is why writes arrived in bursts.

### The same effect in your runtime logs

Your log had a new diagnostic on every reply, and it showed the stall directly:

```
played=2.14s received=94208  written=94208  lost=0 underruns=0 max_gap=1953.0 ms
played=3.34s received=147456 written=147456 lost=0 underruns=0 max_gap=1406.0 ms
played=5.06s received=223232 written=223232 lost=0 underruns=0 max_gap= 782.0 ms
played=2.18s received=96256  written=96256  lost=0 underruns=0 max_gap=1266.0 ms
played=4.64s received=204800 written=204800 lost=0 underruns=0 max_gap=1156.0 ms
played=2.60s received=114688 written=114688 lost=0 underruns=0 max_gap= 594.0 ms
```

Zero bytes lost, zero underruns — and yet **a 0.6–2 second gap between two
consecutive writes**. That is the audio device left with nothing to play, then
flooded, repeatedly. It is exactly what "chopped, stuttering, partly audible,
broken radio" sounds like.

Note the contrast that identified it: a standalone playback test **without a
microphone active** measured a worst-case gap of **63 ms**, because with no
capture thread running `process` was never called. Adding the live capture side
reproduced your 594–1953 ms.

### The fix

* The reference history now has its **own lock** (`_ref_lock`) that the DSP
  never holds. `set_reference` only ever appends to a deque (microseconds, and
  never waits for adaptive-filter work), and `process` takes a fast snapshot
  before computing anything.
* `_estimate_delay` was **vectorised** (`np.correlate` + cumulative-sum window
  energy) — a handful of C-level calls instead of ~2560 numpy calls per chunk —
  which cut the capture thread's CPU from 2.47 ms to 0.23 ms median and removed
  the GIL pressure it was putting on the audio thread.

Result on the real device with a live capture side calling `process`
**260,354 times** (~1,500× the app's contention pressure):

```
utterance 1: received 120832 written 120832  lost 0  underruns 0  MAX_WRITE_GAP_ms: 16.0
utterance 2: received 126976 written 126976  lost 0  underruns 0  MAX_WRITE_GAP_ms: 16.0
```

**From 594–1953 ms down to 16 ms.** The audio thread is no longer stalled.

### Correctness of the rewrite

The vectorised estimator was verified against a known delay, not assumed:

```
locked: True   true_lag: 400   estimated_lag: 400   lag_correct: True
```

The full-path reproduction exercises the real provider, the real player, the
real sound device and a live capture side, and confirms byte-for-byte integrity.

---

## 2. Also fixed: real audio was being deleted (the earlier, worse defect)

`VoicePlayer._play_stream_worker` bounded its jitter buffer by **throwing PCM
away**, via three interacting defects:

1. `jitter_bytes` was incremented by **both** threads for the same bytes (pump
   on enqueue, playback loop again on dequeue) — an unsynchronised `nonlocal`.
2. When that inflated counter passed the cap, the pump drained the queue with
   `get_nowait()` and **discarded** the chunks — never played.
3. Because the counter was ~doubled, the "400 ms" pre-buffer was satisfied with
   ~210 ms, so playback started under-buffered.

Measured: a fast producer against a real-time-paced device discarded
**20,480 of 22,050 bytes (93%)**. In your own runs the player wrote 51,135
bytes where the API had delivered 120,832 — **58% of the reply thrown away**.
Discarding contiguous slices splices the waveform at discontinuities, which is
audible as buzz/clicks in addition to the stalling.

Fixed by bounding the queue by **capacity** with the producer **blocking**
(backpressure) instead of discarding, and by single-owner fill accounting.

---

## 3. Also fixed: normal completion was cancelling playback

`_register_task_cleanup` registered `voice_engine.cancel_all`, and
`Task._finalize()` runs cleanup callbacks for **every** terminal state —
including `SUCCESS`. Your log shows the consequence: playback finished at
`13.476`, `cancel_all` arrived at `13.542`, and the sound device still held
buffered audio, so the final syllable was cut. A bounded, format-derived
**drain on natural completion** now lets the device finish, and TTS teardown is
skipped for a normally-completed turn (still applied to failed/superseded/
interrupted turns). Explicit interruption stays immediate.

---

## 4. Also fixed: partial-frame writes could abort playback

PyAudio rejects a write that is not a whole number of sample frames
(`not a whole number of frames`). An odd-length stream — which does occur; the
duplex's own reference feed guards for it with `len(pcm_chunk) % 2 != 0` — hit
an odd final slice, and the player treated that as `write failed` and **aborted
mid-utterance**. Writes are now aligned to whole sample frames, carrying an
incomplete frame into the next write and flushing a zero-padded tail
(≤ 1 sample). Both write paths are covered.

---

## 5. What was ruled out, and why

* **ElevenLabs / API / account — not the cause.** Measured with your real
  credentials for the exact 58-character reply: `http_status: 200`,
  `content_type: audio/pcm`, **2.647–2.786 s** of audio (~21 chars/s at 1.2x,
  a normal rate), 50 chunks delivered with a **max inter-chunk gap of 47 ms**.
  Valid, correctly-sized, smoothly-delivered audio.
* **Sample format — no mismatch.** `output_format=pcm_22050` → 22050 Hz,
  16-bit, mono; the player opens exactly `paInt16 / 22050 / 1 ch`. No
  resampling on the output path. PCM is not being decoded as encoded audio
  (`Content-Type: audio/pcm`).
* **Clipping / gain / duplicate amplification.** No gain stage exists on the
  output path; bytes go from the HTTP response to `stream.write()` unmodified.
  Verified byte-for-byte that what reaches the device equals what was written,
  so nothing is duplicated. The only consumer of written audio is the echo
  canceller's *reference*, which is a copy.
* **Microphone preprocessing.** The `dc/hp/speech_norm/agc/noise gate` chain
  lives in the capture path; it does not touch playback.
* **`turn_mark` per chunk.** Early-returns via `_completed`/`_seen_stages`, so
  `AUDIO_BYTES_WRITTEN` is logged once per turn (which is why your log shows a
  single `bytes=1024` line), not per chunk.
* **Network starvation.** Max inter-chunk gap from the API was 47 ms.

---

## 6. Files changed

| File | Change |
|---|---|
| `voice/echo_canceller.py` | **the remaining root cause** — reference history under its own lock; audio thread never waits for DSP; `process` takes a snapshot; delay estimator vectorised |
| `voice/player.py` | backpressure instead of dropping PCM; single-owner fill accounting; natural-completion drain; whole-frame-aligned writes; new diagnostics |
| `services/conversation_owner.py` | TTS teardown skipped on normal completion |
| `voice/engine.py` | `datetime.utcnow()` → timezone-aware |
| `tests/test_echo_canceller_threading.py` | **new** — 9 tests pinning the threading contract and the delay estimator |
| `tests/test_audio_stream_integrity.py` | **new** — 7 tests: byte loss, underruns, accounting, short replies, frame alignment, cancellation latency |
| `tests/test_state_recovery.py` | +3 tests for the completion/cancellation race |

---

## 7. Test results

| | |
|---|---|
| EC contention before fix (measured) | audio thread blocked median **7.47 ms**, max **168.74 ms**, 2545 ms total |
| EC contention after fix | median **0.07 ms**, max **0.37 ms**, 17 ms total |
| Delay estimator after rewrite | `true 400 → estimated 400`, locked |
| Full path, real device, live capture side | `lost 0`, `underruns 0`, **max write gap 16 ms** |
| **Live application**, real speech, 3 consecutive replies | `lost=0`, `underruns=0` every time; `max_gap` **78 / 0 / 16 ms** (was 594–1953 ms); a 7.52 s reply played in full |
| **Full suite** | **830 passed, 0 failed**, 14 subtests, 162 s |

---

## 8. Was speaker output verified?

**Partly, and the limit is worth stating plainly: I can measure the audio path
but I cannot hear it.** What is verified, on the real device through the real
API:

* zero bytes lost, zero underruns, byte-for-byte integrity into the device;
* the audio thread is no longer blocked — worst write gap **16 ms** against
  594–1953 ms before, and that was measured with ~1,500× the app's contention
  pressure;
* audio is paced across its real duration, not flushed in bursts.

A "chopped / stuttering / partly audible" defect cannot survive those numbers,
but the final judgement on how it sounds has to be yours.

---

## 9. Your check

Say the same phrase a few times and confirm every word is audible and the
speech is smooth and continuous. Then read the log line per reply:

```
VoicePlayer: stream summary played=...s received=...B written=...B \
             lost=0 underruns=0 max_gap=..ms queue_capacity=86 chunks
```

Healthy values: `lost=0`, `underruns=0`, and **`max_gap` in the tens of
milliseconds** (roughly one device buffer). If `max_gap` is ever hundreds or
thousands of milliseconds again, the audio thread is being blocked by something
and that line will say so.

---

## 10. Found but deliberately NOT changed

The echo canceller **never actually cancels anything**, and this is a
pre-existing defect I did not introduce and did not "fix", because it affects
only the microphone path (barge-in / self-voice), not speaker output, and
changing it is a behavioural change you did not ask for.

The gate is self-blocking:

```python
if not self._delay_locked or self._erle <= _ERLE_EPSILON:
    return mic_chunk          # pass-through, ERLE never computed…
...
self._erle = 10.0 * np.log10(ratio)   # …so this can never be reached
```

`_erle` starts at `0.0`, and it is only computed *after* the check that
requires it to be `> 0`. Measured: 23 consecutive chunks of a perfect echo
signal produced `erle_max = 0.0`. Your logs agree — `erle=0.0 dB` on every line
across every turn, even after `delay_locked=True`.

Consequence: the mic still carries JARVIS's own voice, so self-voice rejection
relies on the downstream suppressor/VAD, and `ERLE` diagnostics are
meaningless. If you want real echo cancellation, the gate needs to allow the
first adapting pass (or seed the delay estimate) — say the word and I will
change it and verify it against a known-delay harness.
