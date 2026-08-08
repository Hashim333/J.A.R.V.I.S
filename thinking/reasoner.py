"""
thinking/reasoner.py — the LLM-driven reasoning layer.

Sits in front of the deterministic rule pipeline.  For every fresh
utterance it consults the local LLM (grounded with recent conversation
memory and the current world state) and produces a structured plan:

    MODE:   ACT | ASK | ANSWER
    intent / entities
    confidence  (0..1)   — how sure the model is about intent + entities
    reasoning   (trace)  — why it chose this mode/action
    question    (ASK)
    answer      (ANSWER)
    alternatives(ACT)    — alternative strategies to try on failure

The reasoner NEVER executes anything itself.  An ACT plan is handed back
to the existing rule pipeline (recognize → decide → plan → confirm →
execute → verify → respond), which preserves every existing safety
property (confirmation gate, world-state verification, cancellation).
An ASK plan is surfaced as a clarification question; the user's answer is
fed back through ``continue_`` so the model re-reasons with the new
information.  An ANSWER plan is returned directly to the user.

Robustness contract
-------------------
The rule pipeline is always the fallback.  If the LLM is unreachable or
its output is unparseable, ``reason()`` / ``continue_()`` return ``None``
and the caller behaves exactly as it did before this layer existed.
"""

from __future__ import annotations

import concurrent.futures
import json
import logging
import re
from dataclasses import dataclass, field
from typing import Any

from brain.llm import LLM
from brain.parser import Parser

logger = logging.getLogger(__name__)

# The concrete intents the executor understands.  The reasoner may only
# emit one of these for ACT, otherwise downstream planning cannot run.
KNOWN_INTENTS: tuple[str, ...] = (
    # applications
    "open_app", "close_app", "focus_app", "restart_app", "minimize_app",
    "maximize_app", "restore_app", "close_all_apps", "is_running",
    # browser
    "open_website", "search", "navigate", "browser_search",
    # files
    "open_file", "find_file", "open_file_location", "copy_file",
    "move_file", "rename_file", "delete_file",
    # media
    "play_music", "play_video",
    "media_pause", "media_resume", "media_next", "media_previous",
    "skip_ad", "like_video", "subscribe_channel", "continue_watching",
    "scroll_page",
    # system
    "open_settings", "open_special_folder", "increase_volume",
    "decrease_volume", "set_volume", "mute_volume", "unmute_volume",
    "screenshot", "lock", "shutdown_windows", "restart", "sleep",
    "sign_out", "cancel_shutdown", "system_status", "set_brightness",
    "wifi_on", "wifi_off", "bluetooth_on", "bluetooth_off",
    "airplane_mode_on", "airplane_mode_off", "open_task_manager",
    "open_device_manager", "open_control_panel", "format_drive",
    "kill_process",
    # vision / screen understanding
    "read_screen", "describe_screen", "click_element", "find_element",
    "read_pdf", "ocr_image", "read_error", "fill_form",
    # security / pentest tooling
    "create_pentest_report", "organize_scan_results",
    "summarize_scan_results", "create_pentest_project",
    # no-op
    "noop",
)

# Reasoner → entity keys used by the planner/executor.
_ENTITY_HINTS: dict[str, str] = {
    "open_app": '{"app_name": "..."}',
    "close_app": '{"app_name": "..."}',
    "focus_app": '{"app_name": "..."}',
    "open_website": '{"website": "..."}',
    "search": '{"query": "...", "provider": "google|youtube|bing|duckduckgo"}',
    "play_music": '{"query": "...", "provider": "youtube"}',
    "play_video": '{"query": "...", "provider": "youtube"}',
    "media_pause": '{}',
    "media_resume": '{}',
    "media_next": '{}',
    "media_previous": '{}',
    "skip_ad": '{}',
    "like_video": '{}',
    "subscribe_channel": '{}',
    "continue_watching": '{}',
    "scroll_page": '{"direction": "down|up"}',
    "set_volume": '{"level": 50}',
    "set_brightness": '{"level": 50}',
    "open_file": '{"file_query": "..."}',
    "find_file": '{"file_query": "..."}',
    "delete_file": '{"file_query": "..."}',
    "rename_file": '{"file_query": "...", "new_name": "..."}',
    "move_file": '{"file_query": "...", "destination": "..."}',
    "kill_process": '{"process": "..."}',
}

_PROMPT = """You are JARVIS, a desktop assistant that controls a Windows computer. You reason about what the user wants before any action.

Decide how to handle the user request by choosing EXACTLY ONE mode:

- ANSWER: The user is chatting or asking a general question. No computer action is needed. Reply naturally in 1-2 short sentences.
- ASK: The request is a possible action but genuinely missing required information (which app, which site, which file, confirm a destructive action). Ask ONE concise clarifying question.
- ACT: The user clearly wants a concrete computer action you can perform. Pick the closest known intent and the entity values.

Never invent an intent that is not in the known list. If the request cannot be mapped to a known intent and is not chat, choose ANSWER and honestly say you cannot do that, or ASK if one question would resolve it.

Confidence: a number 0.0-1.0 describing how sure you are the intent and entities are correct. Be honest — 0.9+ only when unambiguous.

Reasoning: one short sentence explaining your choice.

Alternatives (only for ACT): 1-2 fallback strategies that use DIFFERENT intent/entities if the primary action fails (e.g. "open spotify" failing -> open spotify.com in a browser).

Known intents and their entity shapes:
{intent_hints}

History (recent commands, newest last):
{history}

Current computer state:
{world_state}

Live system state:
{awareness}

User request: {text}

Respond with ONLY a single JSON object, no markdown, no extra text:
{{
  "mode": "ACT" | "ASK" | "ANSWER",
  "intent": "known intent",
  "entities": {{}},
  "confidence": 0.0,
  "reasoning": "short trace",
  "question": "only for ASK",
  "answer": "only for ANSWER",
  "alternatives": [{{"intent": "...", "entities": {{}}, "description": "..."}}]
}}"""

_CONTINUATION_PROMPT = """You are JARVIS, a desktop assistant that controls a Windows computer. A previous request is awaiting clarification and the user has just answered.

Previous request: {original}
Your question: {question}
User's answer: {answer}

Re-decide how to proceed using the SAME rules and JSON format as before.
If the answer resolves the ambiguity, mode is ACT with the concrete intent/entities. If it still is not enough, mode is ASK with a sharper question. If the user declined or changed their mind, mode is ANSWER with a short natural reply.

Known intents:
{intent_hints}

History (recent commands, newest last):
{history}

Live system state:
{awareness}

Respond with ONLY a single JSON object, no markdown, no extra text:
{{
  "mode": "ACT" | "ASK" | "ANSWER",
  "intent": "known intent",
  "entities": {{}},
  "confidence": 0.0,
  "reasoning": "short trace",
  "question": "only for ASK",
  "answer": "only for ANSWER",
  "alternatives": [{{"intent": "...", "entities": {{}}, "description": "..."}}]
}}"""

_JSON_BLOCK = re.compile(r"\{[\s\S]*\}", re.MULTILINE)


@dataclass(frozen=True)
class Alternative:
    """A fallback strategy the pipeline may auto-retry on failure."""

    intent: str
    entities: dict[str, Any] = field(default_factory=dict)
    description: str = ""


@dataclass(frozen=True)
class ReasonedPlan:
    """The reasoner's structured decision for one utterance."""

    mode: str                      # "ACT" | "ASK" | "ANSWER"
    intent: str = ""
    entities: dict[str, Any] = field(default_factory=dict)
    confidence: float = 0.5
    reasoning: str = ""
    question: str = ""
    answer: str = ""
    alternatives: list[Alternative] = field(default_factory=list)
    source: str = "llm"

    @property
    def is_action(self) -> bool:
        return self.mode == "ACT"


class Reasoner:
    """LLM-driven reasoning layer.  Returns ``None`` when the LLM is
    unavailable or its output cannot be parsed, so the caller always has
    the rule pipeline as a safe fallback."""

    def __init__(
        self,
        llm: LLM | None = None,
        parser: Parser | None = None,
        known_intents: tuple[str, ...] = KNOWN_INTENTS,
        timeout: float | None = 6.0,
    ) -> None:
        self._llm = llm or LLM()
        self._parser = parser or Parser()
        self._known_intents = known_intents
        # Bounded LLM call: if the model is slow (e.g. cold start after
        # boot) the reasoner gives up quickly and the rule pipeline takes
        # over, so a slow inference never eats the brain's whole budget.
        # Set to 0 / None to disable the bound.
        self._timeout = timeout

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def reason(
        self,
        text: str,
        memory: Any = None,
        world_state: Any = None,
        awareness: Any = None,
    ) -> ReasonedPlan | None:
        """Reason about a fresh user utterance.

        Returns ``None`` (never raises) when the LLM cannot answer, so the
        caller falls back to the deterministic pipeline untouched.
        """
        if not text or not text.strip():
            return None
        prompt = _PROMPT.format(
            intent_hints=self._intent_hints(),
            history=self._history(memory),
            world_state=self._world_summary(world_state),
            awareness=self._awareness_summary(awareness),
            text=text.strip(),
        )
        return self._ask(prompt, text)

    def continue_(
        self,
        original_text: str,
        question: str,
        answer: str,
        memory: Any = None,
        world_state: Any = None,
        awareness: Any = None,
    ) -> ReasonedPlan | None:
        """Re-reason after the user answers a clarification question."""
        if not answer or not answer.strip():
            return None
        prompt = _CONTINUATION_PROMPT.format(
            original=original_text.strip(),
            question=question,
            answer=answer.strip(),
            intent_hints=self._intent_hints(),
            history=self._history(memory),
            awareness=self._awareness_summary(awareness),
        )
        return self._ask(prompt, original_text)

    # ------------------------------------------------------------------
    # Prompt helpers
    # ------------------------------------------------------------------

    def _intent_hints(self) -> str:
        lines = []
        for intent in self._known_intents:
            hint = _ENTITY_HINTS.get(intent)
            if hint:
                lines.append(f"- {intent}: entities {hint}")
            else:
                lines.append(f"- {intent}: (no entities)")
        return "\n".join(lines)

    @staticmethod
    def _history(memory: Any) -> str:
        if memory is None:
            return "(none)"
        try:
            recent = memory.get_recent_commands(limit=5)
        except Exception:
            return "(none)"
        if not recent:
            return "(none)"
        return "; ".join(getattr(e, "content", str(e)) for e in recent)

    @staticmethod
    def _world_summary(world_state: Any) -> str:
        if world_state is None:
            return "(not provided)"
        try:
            focused = getattr(world_state, "focused_window", None)
            active_site = getattr(world_state, "active_website", None)
            running = [
                a.name for a in getattr(world_state, "applications", [])
            ][:8]
            parts = []
            if focused:
                parts.append(f"focused window: {focused}")
            if active_site:
                parts.append(f"active website: {active_site}")
            if running:
                parts.append("running apps: " + ", ".join(running))
            return "; ".join(parts) if parts else "(none)"
        except Exception:
            return "(none)"

    @staticmethod
    def _awareness_summary(awareness: Any) -> str:
        """Render the live system-awareness snapshot for LLM grounding."""
        if awareness is None:
            return "(not provided)"
        try:
            from system_awareness import describe
            return describe(awareness)
        except Exception:
            return "(not provided)"

    # ------------------------------------------------------------------
    # LLM round-trip
    # ------------------------------------------------------------------

    def _ask(self, prompt: str, raw_text: str) -> ReasonedPlan | None:
        try:
            raw = self._bounded_ask(prompt)
        except Exception as exc:
            logger.warning("Reasoner: LLM unavailable (%s) — falling back to rule pipeline", exc)
            return None
        if raw is None:
            logger.warning("Reasoner: LLM call timed out — falling back to rule pipeline")
            return None
        return self._parse(raw, raw_text)

    def _bounded_ask(self, prompt: str) -> str | None:
        """Call the LLM, returning ``None`` if it exceeds ``self._timeout``.

        Runs the request on a daemon worker so a hung/cold Ollama can never
        block the pipeline past the bound.  ``None`` (timeout) is the
        fallback signal for the caller."""
        if not self._timeout or self._timeout <= 0:
            return self._llm.ask(prompt)

        pool = concurrent.futures.ThreadPoolExecutor(max_workers=1)
        future = pool.submit(self._llm.ask, prompt)
        try:
            return future.result(timeout=self._timeout)
        except concurrent.futures.TimeoutError:
            return None
        finally:
            # Never wait for a still-running request; its worker is a
            # daemon thread and will be discarded.
            pool.shutdown(wait=False)

    def _parse(self, raw: str, raw_text: str) -> ReasonedPlan | None:
        if not raw or not raw.strip():
            logger.warning("Reasoner: empty LLM output")
            return None

        data = self._extract_json(raw)
        if data is None:
            logger.warning("Reasoner: unparseable LLM output — %r", raw[:200])
            return None

        mode = str(data.get("mode", "")).strip().upper()
        if mode not in ("ACT", "ASK", "ANSWER"):
            logger.warning("Reasoner: unknown mode %r", mode)
            return None

        intent = str(data.get("intent", "") or "").strip()
        entities = data.get("entities")
        if entities is None or not isinstance(entities, dict):
            entities = {}

        # ACT requires a known, non-empty intent.
        if mode == "ACT":
            if not intent or intent not in self._known_intents:
                logger.warning("Reasoner: ACT with unknown intent %r — treating as ASK", intent)
                mode = "ASK"
                data["question"] = data.get("question") or (
                    f"You asked me to do something I can't fully understand "
                    f"(\"{raw_text.strip()}\"). Could you rephrase it?"
                )

        confidence = self._clamp_confidence(data.get("confidence"))
        alternatives = self._parse_alternatives(data.get("alternatives"))

        plan = ReasonedPlan(
            mode=mode,
            intent=intent,
            entities=entities,
            confidence=confidence,
            reasoning=str(data.get("reasoning", "") or "").strip(),
            question=str(data.get("question", "") or "").strip(),
            answer=str(data.get("answer", "") or "").strip(),
            alternatives=alternatives,
            source="llm",
        )
        logger.info(
            "Reasoner: mode=%s intent=%s confidence=%.2f alternatives=%d — %s",
            plan.mode, plan.intent or "-", plan.confidence, len(plan.alternatives),
            plan.reasoning or "-",
        )
        return plan

    # ------------------------------------------------------------------
    # Parsing helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _extract_json(raw: str) -> dict[str, Any] | None:
        match = _JSON_BLOCK.search(raw)
        if match is None:
            return None
        try:
            data = json.loads(match.group(0))
        except (json.JSONDecodeError, ValueError):
            return None
        return data if isinstance(data, dict) else None

    @staticmethod
    def _clamp_confidence(value: Any) -> float:
        try:
            number = float(value)
        except (TypeError, ValueError):
            return 0.5
        return max(0.0, min(1.0, number))

    def _parse_alternatives(self, raw: Any) -> list[Alternative]:
        if not isinstance(raw, list):
            return []
        out: list[Alternative] = []
        for item in raw:
            if not isinstance(item, dict):
                continue
            alt_intent = str(item.get("intent", "") or "").strip()
            if not alt_intent or alt_intent not in self._known_intents:
                continue
            alt_entities = item.get("entities")
            if not isinstance(alt_entities, dict):
                alt_entities = {}
            out.append(Alternative(
                intent=alt_intent,
                entities=dict(alt_entities),
                description=str(item.get("description", "") or "").strip(),
            ))
        return out
