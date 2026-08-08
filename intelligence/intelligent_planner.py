"""
intelligence/intelligent_planner.py — world-state-aware action planning.

The Intelligent Planner wraps the deterministic rule-based Planner and
makes it state-aware:

1. **World state consultation** — before returning a plan it checks the
   live computer state (running apps, browser windows, active tab,
   playing media) so it can ask the right question (e.g. "Close the
   current window or all Chrome windows?") instead of blindly executing.

2. **Verification is baked into every plan** — each plan carries a list
   of ``VerificationCheck`` objects describing what must be true after
   execution. The pipeline will not report success unless those checks
   pass, so the planner can never say "Done" without evidence.

3. **Intelligent rewrites** — e.g. a "new browser window" becomes
   "focus the running browser + Ctrl+N", never a second Chrome process.

The planner never executes anything itself; it only produces plans,
verification specs and — when world state demands it — a ``UserChoice``
question for the pipeline to ask.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from brain.execution_plan import ExecutionPlan, Step
from brain.parsed_command import ParsedCommand
from brain.planner import Planner

from intelligence.world_state import BrowserState, WorldState

logger = logging.getLogger(__name__)

# -- Verification contract ---------------------------------------------

_BROWSER_ALIASES: dict[str, str] = {
    "chrome": "chrome",
    "google chrome": "chrome",
    "chromium": "chrome",
    "edge": "msedge",
    "microsoft edge": "msedge",
    "brave": "brave",
    "opera": "opera",
    "vivaldi": "vivaldi",
    "firefox": "firefox",
}

_SEARCH_PROVIDER_DOMAINS: dict[str, str] = {
    "youtube": "youtube.com",
    "google": "google.com/search",
    "bing": "bing.com/search",
    "duckduckgo": "duckduckgo.com",
}


@dataclass(frozen=True)
class VerificationCheck:
    """What must be true after a plan runs for it to count as success."""

    kind: str          # app_running | app_closed | url_loaded | tab_open | media_playing | none
    target: str = ""
    timeout: float = 15.0
    required: bool = True


@dataclass(frozen=True)
class UserChoice:
    """A question the planner needs answered before it can plan."""

    kind: str          # close_window_choice | music_replace
    question: str
    options: list[str]
    context: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class PlanResult:
    """The planner's output: a plan, its verification spec, and any
    user choice the pipeline must ask first."""

    plan: ExecutionPlan
    verification: list[VerificationCheck] = field(default_factory=list)
    user_choice: UserChoice | None = None


class IntelligentPlanner:
    """State-aware planner producing verification-backed plans."""

    def __init__(
        self,
        base_planner: Planner | None = None,
        world_state: Any = None,
    ) -> None:
        self._base = base_planner or Planner()
        self._world_state = world_state

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def create_plan(
        self,
        parsed: ParsedCommand,
        confirmed: bool = False,
        world_state: WorldState | None = None,
    ) -> PlanResult:
        """Build a state-aware plan for a freshly parsed command."""
        ws = world_state if world_state is not None else self._world()
        choice = None if confirmed else self._detect_user_choice(parsed, ws)
        return self.refine(
            self._base.create_plan(parsed, confirmed),
            parsed,
            world_state=ws,
            user_choice=choice,
        )

    def refine(
        self,
        plan: ExecutionPlan,
        parsed: ParsedCommand,
        world_state: WorldState | None = None,
        user_choice: UserChoice | None = None,
    ) -> PlanResult:
        """Add verification + intelligence to an already-built plan.

        Used both by ``create_plan`` and by the pipeline when it rebuilds
        a plan after a clarification answer.
        """
        ws = world_state if world_state is not None else self._world()
        steps = self._apply_intelligence(parsed, plan.steps, ws)
        verification = self._build_verification(parsed, plan, ws)

        metadata = dict(plan.metadata)
        metadata["intelligent"] = True
        metadata["verification"] = [vars(c) for c in verification]

        refined = ExecutionPlan(
            raw_text=plan.raw_text,
            intent=plan.intent,
            confidence=plan.confidence,
            steps=steps,
            metadata=metadata,
        )

        self._log_plan(plan.intent, steps)
        self._log_verification(verification)

        return PlanResult(
            plan=refined,
            verification=verification,
            user_choice=user_choice,
        )

    def build_choice_plan(
        self,
        choice: UserChoice,
        answer: str,
        parsed: ParsedCommand,
    ) -> ExecutionPlan | None:
        """Turn a user's answer to a planner ``UserChoice`` into a plan."""
        answer_lower = answer.strip().casefold()

        if choice.kind == "close_window_choice":
            if "all" in answer_lower or "all window" in answer_lower or "all windows" in answer_lower:
                return self._base.create_plan(parsed, confirmed=True)
            if "current" in answer_lower or "this" in answer_lower:
                browser = choice.context.get("browser", "chrome")
                return self._close_current_window(parsed, browser)
            return None

        if choice.kind == "music_replace":
            if "replace" in answer_lower or "yes" in answer_lower:
                return self._base.create_plan(parsed, confirmed=True)
            if "keep" in answer_lower or "no" in answer_lower:
                return ExecutionPlan(
                    raw_text=parsed.raw_text,
                    intent="noop",
                    confidence=parsed.confidence,
                    steps=[],
                    metadata={"confirmed": True, "noop": True},
                )
            return None

        return None

    # ------------------------------------------------------------------
    # User-choice detection (world state)
    # ------------------------------------------------------------------

    def _detect_user_choice(
        self,
        parsed: ParsedCommand,
        ws: WorldState | None,
    ) -> UserChoice | None:
        if ws is None:
            return None
        intent = parsed.intent

        # "Close Chrome" with several Chrome windows open → ask which.
        if intent == "close_app":
            app_name = parsed.entities.get("app_name", "").strip()
            browser = self._browser_name(app_name)
            if browser is not None:
                windows = ws.browser_windows(browser)
                if len(windows) > 1:
                    bstate = ws.browser(browser)
                    display = bstate.display_name if bstate else browser.title()
                    return UserChoice(
                        kind="close_window_choice",
                        question=(
                            f"{display} has {len(windows)} windows open. "
                            "Close the current window or all of them?"
                        ),
                        options=["Current window", "All windows"],
                        context={"browser": browser, "window_count": len(windows)},
                    )

        # "Play X" while a video is already playing → ask to replace.
        if intent in ("play_music", "play_video"):
            if ws.video_playing:
                b = self._active_browser(ws)
                if b is not None and b.content == "video":
                    return UserChoice(
                        kind="music_replace",
                        question=(
                            "I found music already playing. "
                            "Do you want me to replace it?"
                        ),
                        options=["Replace", "Keep"],
                        context={"browser": b.name},
                    )

        return None

    # ------------------------------------------------------------------
    # Intelligence rewrites
    # ------------------------------------------------------------------

    def _apply_intelligence(
        self,
        parsed: ParsedCommand,
        steps: list[Step],
        ws: WorldState | None,
    ) -> list[Step]:
        """Rewrite naive steps into state-aware ones."""
        out: list[Step] = []
        for step in steps:
            if step.action == "open_app" and step.parameters.get("new_window"):
                target = step.target or ""
                browser = self._browser_name(target)
                if browser is not None and ws is not None and ws.browser_windows(browser):
                    # Never launch a second browser process: focus the
                    # running browser and open a new window with Ctrl+N.
                    display = target
                    out.append(Step(
                        action="focus_app",
                        target=target,
                        parameters={"app_name": target},
                        description=f"Focus {display}.",
                    ))
                    out.append(Step(
                        action="hotkey",
                        parameters={"keys": "ctrl+n"},
                        description="Open a new browser window (Ctrl+N).",
                    ))
                    logger.info(
                        "IntelligentPlanner: rewrote new window for running %s → focus + Ctrl+N",
                        display,
                    )
                    continue
            out.append(step)

        # "Play X" → after the YouTube search, actually open the first
        # non-sponsored result so the video starts playing.
        if parsed.intent in ("play_music", "play_video"):
            self._append_video_play_steps(steps, out)

        return out

    @staticmethod
    def _append_video_play_steps(steps: list[Step], out: list[Step]) -> None:
        """Append a ``click_first_video`` step after the YouTube search."""
        for step in steps:
            if step.action == "search":
                provider = (step.parameters.get("provider") or "").strip().casefold()
                if provider != "youtube":
                    continue
                query = (step.parameters.get("query") or step.target or "").strip()
                if not query:
                    continue
                out.append(Step(
                    action="click_first_video",
                    target=query,
                    parameters={"query": query},
                    description=f"Open the first YouTube result for {query!r}.",
                ))
                logger.info(
                    "IntelligentPlanner: play flow → %s + click_first_video",
                    ", ".join(s.action for s in out),
                )
                return

    # ------------------------------------------------------------------
    # Verification spec
    # ------------------------------------------------------------------

    def _build_verification(
        self,
        parsed: ParsedCommand,
        plan: ExecutionPlan,
        ws: WorldState | None,
    ) -> list[VerificationCheck]:
        intent = parsed.intent
        entities = parsed.entities

        if intent == "open_app":
            target = entities.get("app_name", "")
            if target:
                return [VerificationCheck(kind="app_running", target=target)]
        elif intent == "close_app":
            target = entities.get("app_name", "")
            if target:
                return [VerificationCheck(kind="app_closed", target=target)]
        elif intent == "open_website":
            target = entities.get("url", "") or entities.get("website", "")
            return [VerificationCheck(kind="url_loaded", target=target)]
        elif intent == "search":
            provider = entities.get("provider", "google")
            target = _SEARCH_PROVIDER_DOMAINS.get(
                provider.strip().casefold(), "google.com"
            )
            return [VerificationCheck(kind="url_loaded", target=target)]
        elif intent in ("play_music", "play_video"):
            return [VerificationCheck(kind="media_playing", timeout=20.0)]

        return [VerificationCheck(kind="none")]

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _world(self) -> WorldState | None:
        try:
            if self._world_state is not None:
                return self._world_state.current()
        except Exception as exc:
            logger.warning("IntelligentPlanner: world state unavailable: %s", exc)
        return None

    @staticmethod
    def _browser_name(app_name: str) -> str | None:
        key = app_name.strip().casefold()
        if key in _BROWSER_ALIASES:
            return _BROWSER_ALIASES[key]
        for alias, canonical in _BROWSER_ALIASES.items():
            if alias in key:
                return canonical
        return None

    @staticmethod
    def _active_browser(ws: WorldState) -> BrowserState | None:
        for b in ws.browsers.values():
            if b.running and b.active_url:
                return b
        return None

    def _close_current_window(
        self,
        parsed: ParsedCommand,
        browser: str,
    ) -> ExecutionPlan:
        display = browser.title()
        return ExecutionPlan(
            raw_text=parsed.raw_text,
            intent="close_app",
            confidence=parsed.confidence,
            steps=[
                Step(
                    action="focus_app",
                    target=browser,
                    parameters={"app_name": browser},
                    description=f"Focus {display}.",
                ),
                Step(
                    action="hotkey",
                    parameters={"keys": "alt+f4"},
                    description="Close the focused window (Alt+F4).",
                ),
            ],
            metadata={"confirmed": True, "intelligent": True, "close_scope": "current"},
        )

    # ------------------------------------------------------------------
    # Structured logs
    # ------------------------------------------------------------------

    @staticmethod
    def _log_plan(intent: str, steps: list[Step]) -> None:
        if not steps:
            logger.info("\n---- PLAN ------------\nIntent: %s\n  (no steps)", intent)
            return
        lines = "\n".join(
            f"  {i}. {s.action}" + (f" {s.target}" if s.target else "")
            for i, s in enumerate(steps, 1)
        )
        logger.info("\n---- PLAN ------------\nIntent: %s\n%s", intent, lines)

    @staticmethod
    def _log_verification(checks: list[VerificationCheck]) -> None:
        if not checks:
            return
        lines = "\n".join(
            f"  - {c.kind}" + (f" → {c.target}" if c.target else "")
            for c in checks
        )
        logger.info("---- VERIFICATION ----\n%s", lines)
