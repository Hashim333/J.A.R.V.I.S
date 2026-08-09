"""
thinking/decision_router.py — Decision Engine (CORE-001).

Routes every user request into exactly one of four categories **before**
any reasoning or automation runs:

    LOCAL_COMMAND          — execute immediately, no LLM, no context
    CONTEXT_AWARE_COMMAND  — needs the World Model (active app, running
                             processes, browser state)
    AI_REASONING           — the planner/LLM is genuinely required
    ONLINE_RESEARCH        — only when current/up-to-date information is
                             needed

Design rules
------------
* Local commands (open/close app, volume, media control, system toggles,
  file actions, settings ...) short-circuit without touching the LLM.
* Context-aware commands defer to the World Model and the deterministic
  planner.
* AI reasoning is the fallback for anything the rule engine cannot safely
  resolve (chat, questions, ambiguous/compound requests, report tasks).
* Online research is chosen **only** when the request asks for current
  information (weather, news, live scores, prices, time, ...).

Public API
----------
    engine = DecisionRouter(parser=Parser())
    plan = engine.route(request, context)      # -> ExecutionPlan

``request`` may be a raw ``str``, a ``brain.parsed_command.ParsedCommand``,
or a ``thinking.intent_recognizer.RecognizedIntent``.  ``context`` may be a
``world_model.model.WorldSnapshot``, a plain ``dict``, or ``None``.

Every call is logged with the reason the route was chosen, and a rolling
``decision_history`` is kept for audit / testing.
"""

from __future__ import annotations

import logging
import re
from collections import deque
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

logger = logging.getLogger(__name__)


class RouteCategory(str, Enum):
    """The four routing buckets every request falls into."""

    LOCAL_COMMAND = "LOCAL_COMMAND"
    CONTEXT_AWARE_COMMAND = "CONTEXT_AWARE_COMMAND"
    AI_REASONING = "AI_REASONING"
    ONLINE_RESEARCH = "ONLINE_RESEARCH"


@dataclass(frozen=True)
class ExecutionPlan:
    """The result of routing one request.

    ``handler`` names the subsystem responsible for the request:
    ``"executor.local"``, ``"planner.world_model"``, ``"reasoner"``,
    ``"researcher"``.  The boolean flags make the downstream routing
    decision explicit so callers never re-derive it.
    """

    category: RouteCategory
    intent: str
    raw_text: str
    confidence: float
    reason: str
    handler: str
    needs_llm: bool
    needs_world_model: bool
    needs_online: bool
    signals: tuple[str, ...] = ()
    context_available: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def is_local(self) -> bool:
        return self.category is RouteCategory.LOCAL_COMMAND

    @property
    def is_context_aware(self) -> bool:
        return self.category is RouteCategory.CONTEXT_AWARE_COMMAND

    @property
    def is_ai_reasoning(self) -> bool:
        return self.category is RouteCategory.AI_REASONING

    @property
    def is_online_research(self) -> bool:
        return self.category is RouteCategory.ONLINE_RESEARCH


# ---------------------------------------------------------------------------
# Intent buckets
# ---------------------------------------------------------------------------

#: Intents that are pure local system actions — deterministic, no LLM,
#: no world model required.  These are exactly the "everyday commands".
_LOCAL_COMMAND_INTENTS: frozenset[str] = frozenset({
    # Applications (explicitly local per spec)
    "open_app", "close_app",
    # Volume / media control
    "increase_volume", "decrease_volume", "set_volume", "mute_volume",
    "unmute_volume",
    "media_pause", "media_resume", "media_next", "media_previous",
    "skip_ad", "like_video", "subscribe_channel", "continue_watching",
    "scroll_page",
    # System toggles / status
    "screenshot", "lock", "sleep", "restart", "shutdown_windows",
    "shutdown", "sign_out", "cancel_shutdown",
    "set_brightness", "wifi_on", "wifi_off", "bluetooth_on",
    "bluetooth_off", "airplane_mode_on", "airplane_mode_off",
    # Settings / folders / management UIs
    "open_settings", "open_special_folder", "open_task_manager",
    "open_device_manager", "open_control_panel",
    # File actions
    "open_file", "find_file", "open_file_location", "copy_file",
    "move_file", "rename_file", "delete_file",
    # Raw input
    "hotkey", "type_text", "move_mouse", "click", "scroll",
})

#: Intents whose execution depends on the World Model (active app, running
#: processes, browser state, system/media state).
_CONTEXT_AWARE_INTENTS: frozenset[str] = frozenset({
    # Window / process awareness
    "focus_app", "restart_app", "minimize_app", "maximize_app",
    "restore_app", "close_all_apps", "kill_process", "format_drive",
    "is_running",
    # Browser state
    "open_website", "search", "navigate", "browser_search",
    # Media / playback state
    "play_music", "play_video",
    # System / screen state
    "system_status",
    "read_screen", "describe_screen", "click_element", "find_element",
    "read_pdf", "ocr_image", "read_error", "fill_form",
})

#: Intents that always require genuine reasoning (LLM / planner).
_REASONING_INTENTS: frozenset[str] = frozenset({
    "unknown", "ambiguous", "compound",
    "create_pentest_report", "organize_scan_results",
    "summarize_scan_results", "create_pentest_project",
})

# ---------------------------------------------------------------------------
# Current-information markers (Online Research)
# ---------------------------------------------------------------------------

#: Phrases that signal a request for *current* / *up-to-date* information.
#: Present in a search query (or an otherwise-unrecognised utterance) the
#: request is routed to Online Research; otherwise it is context-aware or
#: AI reasoning.
_CURRENT_INFO_PHRASES: tuple[str, ...] = (
    "weather", "forecast", "temperature", "humidity",
    "news", "headlines", "headline", "breaking",
    "today", "tomorrow", "tonight", "right now", "current",
    "live", "score", "scores", "match", "fixture", "standings",
    "price", "prices", "stock", "stocks", "market", "bitcoin",
    "crypto", "cryptocurrency", "election", "results", "result",
    "time in", "time now", "what time", "schedule", "calendar",
    "currency", "exchange rate", "traffic",
)

_CURRENT_INFO_PATTERN = re.compile(
    r"\b(" + "|".join(re.escape(p) for p in _CURRENT_INFO_PHRASES) + r")\b",
    re.IGNORECASE,
)


def _has_current_info_marker(text: str) -> bool:
    return bool(_CURRENT_INFO_PATTERN.search(text))


class DecisionRouter:
    """Routes every user request into one of the four route categories.

    The router is stateless except for a rolling decision log.  A parser
    can be injected so tests (and headless callers) control intent
    resolution; by default ``brain.parser.Parser`` is used.
    """

    def __init__(self, parser: Any | None = None) -> None:
        from brain.parser import Parser

        self._parser = parser if parser is not None else Parser()
        self._decision_history: deque[dict[str, Any]] = deque(maxlen=200)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def route(self, request: Any, context: Any = None) -> ExecutionPlan:
        """Route *request* into an :class:`ExecutionPlan`.

        Args:
            request: raw ``str``, ``ParsedCommand`` or ``RecognizedIntent``.
            context: optional ``WorldSnapshot`` or ``dict`` describing the
                current computer state.

        Returns:
            A frozen :class:`ExecutionPlan` with the chosen route, the
            reason it was chosen, and the target handler.
        """
        intent, entities, raw_text, confidence = self._coerce_request(request)

        signals: list[str] = []
        query = self._search_query(intent, entities, raw_text)

        # -- 1. Online research: only when current information is needed --
        if intent in ("search", "browser_search") and _has_current_info_marker(query):
            signals.append("search_query_requests_current_info")
            return self._emit(
                RouteCategory.ONLINE_RESEARCH, intent, raw_text, confidence,
                reason=(
                    f"Search '{query}' asks for current information — "
                    "routed to Online Research."
                ),
                signals=signals, context=context,
            )

        if intent in _REASONING_INTENTS and intent in ("unknown", "ambiguous"):
            if _has_current_info_marker(raw_text):
                signals.append("unrecognised_but_current_info_marker")
                return self._emit(
                    RouteCategory.ONLINE_RESEARCH, intent, raw_text, confidence,
                    reason=(
                        f"Unrecognised utterance '{raw_text}' requests current "
                        "information — routed to Online Research."
                    ),
                    signals=signals, context=context,
                )

        # -- 2. Local commands: immediate, no LLM --
        if intent in _LOCAL_COMMAND_INTENTS:
            signals.append("deterministic_local_intent")
            return self._emit(
                RouteCategory.LOCAL_COMMAND, intent, raw_text, confidence,
                reason=(
                    f"Intent '{intent}' is a deterministic local command — "
                    "executes immediately without the LLM."
                ),
                signals=signals, context=context,
            )

        # -- 3. Context-aware commands: defer to the World Model --
        if intent in _CONTEXT_AWARE_INTENTS:
            signals.append("requires_world_model_context")
            return self._emit(
                RouteCategory.CONTEXT_AWARE_COMMAND, intent, raw_text,
                confidence,
                reason=(
                    f"Intent '{intent}' depends on the World Model (active app, "
                    "processes, browser/media state)."
                ),
                signals=signals, context=context,
            )

        # -- 4. Fallback: genuine reasoning is required --
        signals.append("no_safe_rule_path")
        return self._emit(
            RouteCategory.AI_REASONING, intent, raw_text, confidence,
            reason=(
                f"Intent '{intent}' has no safe rule path — the LLM reasoner "
                "is required to resolve it."
            ),
            signals=signals, context=context,
        )

    # ------------------------------------------------------------------
    # Request normalisation
    # ------------------------------------------------------------------

    def _coerce_request(self, request: Any) -> tuple[str, dict[str, Any], str, float]:
        """Return ``(intent, entities, raw_text, confidence)`` for any
        supported request shape.  Never raises."""
        if request is None:
            return "unknown", {}, "", 0.0

        if isinstance(request, str):
            return self._parse_text(request)

        intent = getattr(request, "intent", None)
        entities = getattr(request, "entities", {})
        raw_text = getattr(request, "raw_text", None)
        confidence = getattr(request, "confidence", 1.0)

        if not isinstance(intent, str) or not intent:
            # e.g. a RecognizedIntent-like object without .intent
            text = getattr(request, "text", None)
            if isinstance(text, str) and text:
                return self._parse_text(text)
            return "unknown", dict(entities or {}), str(raw_text or ""), float(confidence or 0.0)

        return (
            intent,
            dict(entities or {}),
            str(raw_text or ""),
            float(confidence if confidence is not None else 1.0),
        )

    def _parse_text(self, text: str) -> tuple[str, dict[str, Any], str, float]:
        try:
            parsed = self._parser.parse(text)
        except Exception as exc:  # noqa: BLE001
            logger.warning("DecisionRouter: parser failed for %r: %s", text, exc)
            parsed = None
        if parsed is None:
            return "unknown", {}, text, 0.0
        return parsed.intent, dict(parsed.entities), parsed.raw_text, parsed.confidence

    @staticmethod
    def _search_query(intent: str, entities: dict[str, Any], raw_text: str) -> str:
        query = entities.get("query")
        if isinstance(query, str) and query:
            return query
        return raw_text or ""

    # ------------------------------------------------------------------
    # Plan emission + logging
    # ------------------------------------------------------------------

    def _emit(
        self,
        category: RouteCategory,
        intent: str,
        raw_text: str,
        confidence: float,
        reason: str,
        signals: list[str],
        context: Any,
    ) -> ExecutionPlan:
        handler, needs_llm, needs_world, needs_online = self._handler_for(category)
        context_available = self._context_available(context)

        plan = ExecutionPlan(
            category=category,
            intent=intent,
            raw_text=raw_text,
            confidence=confidence,
            reason=reason,
            handler=handler,
            needs_llm=needs_llm,
            needs_world_model=needs_world,
            needs_online=needs_online,
            signals=tuple(signals),
            context_available=context_available,
        )

        record = {
            "category": category.value,
            "intent": intent,
            "raw_text": raw_text,
            "confidence": confidence,
            "reason": reason,
            "signals": tuple(signals),
            "context_available": context_available,
        }
        self._decision_history.append(record)
        logger.info(
            "ROUTE %-24s intent=%-18s handler=%-18s context=%s — %s",
            category.value, intent or "?", handler, context_available, reason,
        )
        return plan

    @staticmethod
    def _handler_for(category: RouteCategory) -> tuple[str, bool, bool, bool]:
        return {
            RouteCategory.LOCAL_COMMAND: ("executor.local", False, False, False),
            RouteCategory.CONTEXT_AWARE_COMMAND: ("planner.world_model", False, True, False),
            RouteCategory.AI_REASONING: ("reasoner", True, False, False),
            RouteCategory.ONLINE_RESEARCH: ("researcher", True, False, True),
        }[category]

    @staticmethod
    def _context_available(context: Any) -> bool:
        if context is None:
            return False
        if isinstance(context, dict):
            return bool(context)
        # WorldSnapshot and friends are always truthy; an empty application
        # list still counts as "world model is running".
        return bool(getattr(context, "timestamp", None)) or True

    # ------------------------------------------------------------------
    # Audit
    # ------------------------------------------------------------------

    @property
    def decision_history(self) -> list[dict[str, Any]]:
        """Rolling log of every routing decision (oldest first)."""
        return list(self._decision_history)
