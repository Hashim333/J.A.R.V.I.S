# BRAIN-001 — Professional Cognitive Brain Architecture

> **Status:** Design only. No code changes.
> **Scope:** Redesign JARVIS's brain into 9 cognitive layers and deliver the 10 requested architecture artifacts.
> **Reference:** current `PipelineEngine` in `thinking/pipeline.py` (the 5-gate pipeline), `brain/brain.py` (thin facade), `intelligence/intelligent_planner.py`, `executor/executor.py`, `world_model/model.py`, `response/human_layer.py`, `working_memory/working_memory.py`, `memory/*` (stubs), `background/*` (stubs), `monitoring/*`.

---

## 0. The 9 Cognitive Layers (from the task brief)

| Layer | Responsibility | Answers the question |
|---|---|---|
| **1. Perception** | Sense the computer and the user's input | "What is happening now?" |
| **2. Understanding** | Classify the request, extract intent + entities, build context | "What does the user want?" |
| **3. Reasoning** | Decide what to do, when to ask, when to refuse, shortest path | "What should I do about it?" |
| **4. Planning** | Build a safe, verification-backed action plan | "How do I do it safely?" |
| **5. Verification** | Check the plan will work / actually worked against live world state | "Is it true / did it happen?" |
| **6. Execution** | Carry out each plan step via a handler, respecting safety policy | "Do it." |
| **7. Reflection** | Analyze what happened after each action | "How did it go?" |
| **8. Memory** | Store what matters and recall it when needed | "What do I remember?" |
| **9. Learning** | Improve future behavior from outcomes + user feedback | "What did I learn?" |

---

## 1. Deliverable 1 — Architecture Diagram

```
                          ┌──────────────────────────────────────────────┐
                          │                  USER (voice / text)         │
                          └──────────────────────┬───────────────────────┘
                                                 │ raw input
                                                 v
        ┌────────────────────────────────────────────────────────────────┐
        │  [L1] PERCEPTION                                                 │
        │   · Speech: microphone → VAD → STT (word confidences)           │
        │   · WorldModel background snapshots (apps, browser, files,       │
        │     system, media) + SystemAwareness collectors                  │
        │   · Passive events (clipboard, media, network, battery)          │
        └──────────────────────────────┬──────────────────────────────────┘
                                       v raw_text + WorldSnapshot
        ┌────────────────────────────────────────────────────────────────┐
        │  [L2] UNDERSTANDING                                              │
        │   · UtteranceClassifier → UtteranceCategory + confidence         │
        │   · Parser intents + entity extraction (apps, files, urls)      │
        │   · Context fusion (context_manager + WorkingMemory)             │
        └──────────────────────────────┬──────────────────────────────────┘
                                       v (intent, entities, context, confidence)
        ┌────────────────────────────────────────────────────────────────┐
        │  [L3] REASONING                                                 │
        │   · SystemAwareness gate (deterministic instant answers)        │
        │   · Skill awareness gate                                        │
        │   · Deterministic local command gate (no LLM)                   │
        │   · LLM Reasoner gate → MODE: ACT | ASK | ANSWER                │
        │   · Safety risk triage (DANGEROUS category ⇒ confirmation)      │
        └──────────────────────────────┬──────────────────────────────────┘
                                       v ReasonedPlan (ACT)
        ┌────────────────────────────────────────────────────────────────┐
        │  [L4] PLANNING                                                  │
        │   · Planner (rules) + IntelligentPlanner (world-state aware)    │
        │   · Produces ExecutionPlan + VerificationCheck[] + UserChoice   │
        └──────────────────────────────┬──────────────────────────────────┘
                                       v plan + verification spec
        ┌────────────────────────────────────────────────────────────────┐
        │  [L5] VERIFICATION (pre-execution)                              │
        │   · SafetyPolicy checks, validator (paths, apps, urls, params)  │
        │   · Can the target be reached? (ask question if ambiguous)      │
        └──────────────────────────────┬──────────────────────────────────┘
                                       v confirmed/validated plan
        ┌────────────────────────────────────────────────────────────────┐
        │  [L6] EXECUTION                                                 │
        │   · Executor → Registry handler per step                       │
        │   · Confirmation gate, cancel_event, audit log, retry           │
        └──────────────────────────────┬──────────────────────────────────┘
                                       v ActionResult
        ┌────────────────────────────────────────────────────────────────┐
        │  [L5] VERIFICATION (post-execution)                             │
        │   · Check VerificationCheck[] against live WorldModel          │
        │   · success/retry/recover decision                             │
        └──────────────────────────────┬──────────────────────────────────┘
                                       v outcome
        ┌────────────────────────────────────────────────────────────────┐
        │  [L7] REFLECTION                                                │
        │   · outcome analysis, cause classification, retry/recover       │
        │   · emit stats (recognition, planner, recovery success)         │
        └──────────────────────────────┬──────────────────────────────────┘
                                       v lessons + stats
        ┌────────────────────────────────────────────────────────────────┐
        │  [L8] MEMORY + [L9] LEARNING                                    │
        │   · WorkingMemory (short-term) → LongMemory (SQLite/JSON)       │
        │   · Preferences, habits, task outcomes → Learner                │
        └──────────────────────────────┬──────────────────────────────────┘
                                       v natural response
        ┌────────────────────────────────────────────────────────────────┐
        │  RESPONSE (response/human_layer.py)                             │
        │   · humanize/translate/sanitize — never leaks internals         │
        └──────────────────────────────┬──────────────────────────────────┘
                                       v
                          ┌──────────────────────────────────────────────┐
                          │                USER  ▲ conversation          │
                          └──────────────────────────────────────────────┘
```

Cross-cutting:
- **`services/conversation_manager.py`** owns the state machine (STANDBY → IDLE → WAKE → LISTENING → THINKING → SPEAKING → EXECUTING → ACTIVE_CONVERSATION → …). It drives the layer flow per utterance.
- **`monitoring/instrumentation.py` (`@timed`)**, **`monitoring/performance.py` (`log_duration`)**, **`monitoring/pipeline_trace.py`** (`stage_entry/stage_exit`) tag every layer — the source for latency and self-improvement stats.
- **`brain/brain.py`** remains the thin facade; `resolve_context()` (line 208) feeds layers 2–4.

---

## 2. Deliverable 2 — Target Folder Structure

Current → target mapping. Keep existing modules where they already implement a layer; add what is missing.

```
brain/
  brain.py                  # facade (keep, thin) — resolves context, delegates
  planner.py                # rule-based Planner (keep)           → L4
  execution_plan.py         # ExecutionPlan / Step (keep)
  parsed_command.py         # ParsedCommand (keep)
  llm.py                    # LLM gateway (keep)
  parser.py                 # Parser (keep)                       → L2
brain/
  executor/                 # Executor + Registry (keep)          → L6
intelligence/
  intelligent_planner.py    # world-state-aware planner + VerificationCheck (keep) → L4/L5
  world_state.py            # active app/browser/media state (keep) → L1
  reasoning/                # (optional future split of reasoner)
  reinforcement/            # (future) L9
world_model/
  world_model.py            # background snapshot service (keep)   → L1
  model.py                  # frozen WorldSnapshot dataclasses (keep)
system_awareness/
  system_awareness.py       # 14 deterministic collectors (keep)  → L3 fast-path
thinking/
  pipeline.py               # → split: keep as thin orchestrator calling layers
  utterance_classifier.py   # UtteranceClassifier (keep/extend)   → L2
  reasoner.py               # LLM Reasoner (keep)                 → L3
  context_manager.py        # context fusion (keep)               → L2
  confirmation.py           # ConfirmationEngine (keep)           → L5/L6
  verification_engine.py    # post-execution verification (keep)  → L5
executor/                   # (already top-level)
skills/
  registry.py               # persistent skill registry (keep)    → L3/L4
  manager.py                # skill manager (keep)
verification/
  task_verifier.py          # generic verification checks (extend) → L5
working_memory/
  working_memory.py         # short-term TTL memory (keep)        → L8
memory/                     # stubs today → DESIGN (see §7)
  database.py               # (new) SQLite connection layer
  short_memory.py           # (new) session memory bridge
  long_memory.py            # (new) long-term store
  preferences.py            # (new) user preferences store
background/                 # stubs today → DESIGN (see §7, §10)
  notifications.py          # (new) event-driven notifications
  watchdog.py               # (new) idle/resource watchdog
cognition/                  # (NEW — the 9-layer brain orchestrator)
  __init__.py
  engine.py                 # CognitionEngine: drives 1→9 per utterance
  perception.py             # L1 facade: assembles input + WorldSnapshot
  understanding.py          # L2 facade over classifier+parser+context
  reasoning.py              # L3 facade over gates + reasoner
  planning.py               # L4 facade over planners
  verification.py           # L5 facade (pre/post)
  execution.py              # L6 facade over executor
  reflection.py             # L7 (new)
  memory.py                 # L8 facade
  learning.py               # L9 (new)
response/
  human_layer.py            # HumanResponseManager (keep) — the ONLY
                            #   user-facing speech path (CONVERSATION §5)
services/
  conversation_owner.py     # loop owner (keep)
  conversation_manager.py   # state machine (keep/extend)
monitoring/
  instrumentation.py        # Timer/@timed (keep)
  performance.py            # log_duration (keep)
  pipeline_trace.py         # stage_entry/stage_exit (keep)
  watchdog.py               # resource watchdog (keep)
```

---

## 3. Deliverable 3 — Module Responsibilities

| Module | Layer | Responsibilities | Boundaries / never does |
|---|---|---|---|
| `cognition/perception.py` | L1 | Assemble raw text + `WorldSnapshot` + system metrics + passive events into a single `PerceptionInput` | Never decides; never calls LLM |
| `cognition/understanding.py` | L2 | Wrap `UtteranceClassifier` (→ category + confidence), `Parser` (→ intent + entities), `ContextManager` (→ context); produce `UnderstandingResult{intent, entities, category, confidence, context}` | Never plans or executes |
| `cognition/reasoning.py` | L3 | Run the gates in order: system-awareness → skill → deterministic local → LLM Reasoner; triage risk; decide ACT/ASK/ANSWER/REFUSE; produce `ReasonedPlan` | Never executes directly; rule path always the fallback |
| `cognition/planning.py` | L4 | Call `Planner.create_plan` then `IntelligentPlanner.refine`; emit `PlanResult{plan, verification[], user_choice}` | Never executes; asks via `UserChoice` only |
| `cognition/verification.py` | L5 | Pre-exec: policy/validator; post-exec: check `VerificationCheck[]` against live `WorldSnapshot`; return pass/fail + evidence | Never mutates state to make a check pass |
| `cognition/execution.py` | L6 | Invoke `Executor.execute` with cancel_event; wrap `ActionResult` | Never plans; never fakes success |
| `cognition/reflection.py` | L7 | Classify outcome (success/failure/cancelled/clarified); extract cause; emit stats | Never invents facts not present in the outcome |
| `cognition/memory.py` | L8 | Read/write WorkingMemory (session) + long memory (durable) + preferences | No unbounded growth; TTL + caps |
| `cognition/learning.py` | L9 | Update habit/preference/stats tables from Reflection + user feedback | No data leaves the machine (anonymous) |
| `cognition/engine.py` | All | Orchestrate 1→9 in one call; enforce timeouts (`_run_with_timeout`, 20 s); manage cancel | No business logic of its own |

---

## 4. Deliverable 4 — Data Flow

Per-utterance data flow (end to end):

1. **Perception** → `PerceptionInput(text=raw, snapshot=WorldSnapshot, mic_conf=word_confidences, sys=SystemInfo, events=[...])`
2. **Understanding** → `UnderstandingResult(intent, entities{app,file,url,...}, category, confidence, context)`
3. **Reasoning** → `ReasonedPlan(mode=ACT|ASK|ANSWER, action=..., entities, confidence, reasoning_trace, alternatives[], question?, answer?)`
   - If `mode == ASK` → response question → back through `continue_()`.
   - If `mode == ANSWER` → direct humanized response → **stop** (no planning/execution).
4. **Planning** → `PlanResult(plan: ExecutionPlan, verification: VerificationCheck[], user_choice?)`
   - If `user_choice` → ask one question, rebuild plan on answer.
5. **Verification (pre)** → validated plan (paths, apps, urls, params pass `SafetyPolicy` + validators).
6. **Execution** → `ActionResult(success, message, data, verification, duration_ms, retry_count, ...)`
7. **Verification (post)** → `VerificationOutcome(ok, checks_passed[], checks_failed[], evidence)`
8. **Reflection** → `ReflectionReport(outcome, cause, retried, recovered, lesson)`
9. **Memory/Learning** → persist to WorkingMemory + long memory + stats.
10. **Response** → `HumanResponseManager.humanize(result)` → natural language to user.

Data hand-off contracts (types) must be frozen dataclasses (`world_model/model.py` pattern), so layers are independently testable.

---

## 5. Deliverable 5 — Conversation Rules (from the brief, enforced)

The user-facing assistant must NEVER say: *pipeline / planner / executor / verification / task failed / intent / internal state*.

Enforcement point: **every** user-facing string goes through `response/human_layer.py` (`HumanResponseManager.humanize/translate/sanitize`, `HUMAN_MESSAGES`, `SAFE_FALLBACK`). No other component may speak to the user.

Forbidden → natural phrasing table:

| Forbidden internal term | Natural phrasing |
|---|---|
| "Task failed" | "I couldn't do that." |
| "Verification failed" | "That didn't seem to work — I'll try another way." |
| "Planner/plan error" | "I couldn't work out how to do that." |
| "Executor error" | "I ran into a problem doing that." |
| "Classification / intent unknown" | "I'm not sure what you meant — can you say that differently?" |
| "Internal state / context error" | "Let me try that again." |

This is already the contract of `HumanResponseManager`; the redesign makes it the **single choke point** and extends its safe fallback set. The pipeline's technical messages are marked as *internal* and only surfaced when `JARVIS_DIAG=1` is set (diagnostics), never in normal conversation.

---

## 6. Deliverable 6 — Decision Flow

Decision principles (from the brief): fastest, fewest clicks, least interruption, highest confidence, lowest risk. Ask **one short question** when confidence is low; never guess.

```
ReasonedPlan decision ladder
────────────────────────────
1. Is it a known instant-answer / system question?        → answer directly (no LLM)
2. Is it a skill?                                         → skill path
3. Is it a deterministic local command with high confidence? → execute
4. LLM Reasoner confidence ≥ threshold?
     └─ no → ask ONE short question → re-reason (continue_)
5. Risk triage:
     └─ dangerous/irreversible (format, delete, shutdown, kill) → require confirmation
6. Ambiguity that changes outcome (close all vs one window, replace music)?
     └─ ask one choice question (UserChoice)
7. Otherwise → plan → verify → execute → verify → reflect.
```

Decision record: every decision (gate taken, confidence, mode, ask/reason) is appended to `monitoring/pipeline_trace.py` trace for diagnostics + stats, not for the user.

---

## 7. Deliverable 7 — Memory Flow (L8) — the design gap

**Today:** `working_memory/working_memory.py` is a solid TTL-bounded short-term store (singleton + list types, eviction thread). `memory/` is stub territory (empty `database.py`, `long_memory.py`, `preferences.py`, `short_memory.py`). `skills/registry.py` already persists skills to JSON.

**Target memory tiers:**

| Tier | Store | Data | Lifecycle |
|---|---|---|---|
| Session | `WorkingMemory` | current task/project/app/file/tab/folder, recent commands/actions, conversation context | TTL + eviction thread (existing) |
| Episodic | `memory/long_memory.py` → SQLite | task outcomes, what worked/failed (summary) | append-only, capped/pruned |
| Semantic | `memory/preferences.py` → SQLite | user preferences, learned defaults, habits (frequent app/folder) | upsert, versioned |
| Procedural | `skills/registry.py` (existing JSON) | skills, aliases, capabilities | registry-managed |

**Write path (after Reflection):**
```
ReflectionReport → memory/learning.py →
    WorkingMemory.add_* (session context)
    long_memory.record_outcome(task, ok, cause, duration)
    preferences.learn(...) / habits.observe(...)     (anonymous, capped)
    if user corrected behavior → preferences.apply(user_hint)  # never hardcoded
```

**Read path (before Planning):**
```
Planning needs preference? → cognition/memory.py .preferences_for(intent)
Context resolution → brain.resolve_context() → WorkingMemory singleton reads
```

**Constraints:** memory reads are synchronous & cheap; writes are async/deferred; all stores bounded (cap counts, prune oldest); never store raw transcripts unless user opts in.

---

## 8. Deliverable 8 — Recovery Flow (L7 + L5)

On post-execution verification failure:

```
Verify fails → VerificationOutcome(ok=False, checks_failed=[...])
Reflection.classify_failure(cause=app_not_found | url_error | permission |
                            state_conflict | transient | unknown)
├── transient / close alternative → RETRY once with LLM alternative
│       (existing auto-retry-once path in pipeline, §n)
│       retry success → recover: report naturally, continue
├── retry fails / cause structural →
│       stop acting; ask user one short question
│       ("I couldn't find Chrome — should I open the website in Edge instead?")
│       user answers → rebuild plan (planner.continue_)
├── dangerous/irreversible failed mid-way → roll back / report "I stopped before
│       finishing that."  → never leave partial destructive state
└── always: record recovery attempt + outcome in stats
        (recovery_success_rate = recovered / (recovered+unrecovered))
```

Rules: max 1 auto-retry per utterance; never retry a destructive step without confirmation; user can always cancel (cancel_event checked every step).

---

## 9. Deliverable 9 — Reflection Flow (L7) — the new layer

Triggered after every response/action (including ASK/ANSWER/REFUSE and failures).

```
ReflectionEngine.reflect(outcome, result, trace) →
 1. outcome = SUCCESS | FAILURE | PARTIAL | CANCELLED | CLARIFIED | REFUSED
 2. cause = classification (for failures): app_missing | network | permission |
            ambiguity | state_mismatch | timeout | llm | unknown
 3. time = result.duration_ms (per layer from @timed traces)
 4. emit anonymous stats:
      - most_used_commands (intent frequency)
      - avg_execution_time (per intent, rolling)
      - recognition_accuracy (mic word_confidences + classifier confidence)
      - recovery_success
      - planner_success (verify ok / plans attempted)
 5. learning hooks:
      - success pattern → habits/preferences
      - repeated failure on same intent → adjust planner/prefer alternative
      - user correction → store preference (never hardcode)
 6. emit humanized response via HumanResponseManager (may ask follow-up)
```

Reflection is fire-and-forget / async so it never delays the user response.

---

## 10. Deliverable 10 — Future Scalability

- **Multi-modal perception** — vision/OCR (read_screen, ocr_image already in intents), PDF reading, notifications feed → extend `PerceptionInput`; all via L1, no downstream changes.
- **Events not polling** — today `WorldModel` polls. Target: push updates (window focus, media, clipboard, network) through an in-process event bus; polling only as fallback for sources without events. Meets idle CPU < 1%.
- **Memory tiers** — `memory/` stubs become the SQLite-backed store in §7; schema versioned for upgrades.
- **Reinforcement / learning (L9)** — `intelligence/reinforcement/` can later consume Reflection stats to re-rank planner choices; keep stats anonymous and local.
- **Skills as plugins** — `skills/registry.py` + `automation/` already registry-based; new handlers = new registry entries (no brain changes).
- **Background / scheduled actions** — `background/notifications.py` + `background/watchdog.py` grow into event-driven reminders + idle resource guard (idle RAM < 200 MB target).
- **Multi-conversation / multi-device** — `services/conversation_manager.py` state machine + `cognition/engine.py` are single-tenant; keep the layer interfaces frozen so a session/tenant envelope can be added later without touching layers.
- **Load budget** (from brief): idle CPU < 1%, idle RAM < 200 MB, reasoning only when needed (deterministic gates before LLM), events instead of polling → each new subsystem must declare its idle cost in a `perf_budget` table reviewed at integration.

---

## Appendix — Existing ground truth used by this design

| Current artifact | Location | Role in the 9 layers |
|---|---|---|
| `Brain` facade | `brain/brain.py:32` (init), `:186` (process), `:208` (resolve_context) | Orchestration entry |
| `PipelineEngine` | `thinking/pipeline.py:61`, `_process_inner :146` | Current 5-gate flow → becomes `cognition/engine.py` |
| Gates | `pipeline.py:228` (system awareness), `:260` (skill), `:329` (deterministic, no LLM), `:362` (LLM reasoner), `:200` (classification) | L3 |
| Context switch | `pipeline.py:1135/1175/1196` | L2/L3 |
| Verify + auto-retry | `pipeline.py:1863` (verify), `:807` (auto-retry once) | L5/L7 |
| `UtteranceClassifier` | `thinking/utterance_classifier.py:224`; categories at `:40` | L2 |
| `Reasoner` | `thinking/reasoner.py` (ACT/ASK/ANSWER) | L3 |
| `IntelligentPlanner` | `intelligence/intelligent_planner.py:91`; `VerificationCheck :61`, `PlanResult :81` | L4/L5 |
| `Executor` | `executor/executor.py:36` (`execute :60`) | L6 |
| `WorldSnapshot` | `world_model/model.py:82` (frozen dataclasses) | L1/L5 |
| `HumanResponseManager` | `response/human_layer.py` | CONVERSATION gate |
| `WorkingMemory` | `working_memory/working_memory.py:66` | L8 session tier |
| `ConversationManager` | `services/conversation_manager.py:45`, states `:14` | State machine |
| Monitoring | `monitoring/instrumentation.py`, `performance.py`, `pipeline_trace.py`, `watchdog.py` | Stats / perf |
| `memory/` + `background/` | stubs | L8 (long-term) + future scalability |

**Gap summary (what the redesign adds beyond today's code):**
1. `cognition/` layer facades + `engine.py` (formal 1→9 orchestration).
2. `reflection.py` (L7) — not present today; today only retry-once + logs.
3. `learning.py` (L9) + long-term `memory/` stores (L8 durable tier) — stubs today.
4. Pre-execution `VerificationCheck[]` gate (L5 pre) — exists partially in validator; formalized in design.
5. Anonymous stats aggregation (recognition/planner/recovery success) — today only raw `@timed` traces.
6. Events-not-polling perception (idle CPU target) and `background/` scheduled actions.

*Design ends here. No code changes are part of BRAIN-001.*
