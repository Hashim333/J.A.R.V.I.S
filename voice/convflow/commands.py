"""
voice/pipeline/commands.py

``CommandDispatcher`` — runs one command without ever blocking the UI or the
voice thread.

Heavy work (planning, reasoning, any automation actions) is delegated to a
worker and bounded by a watchdog-backed deadline.  The pipeline hands a
``CommandResult`` back with the produced response and a flag describing
whether a confirmation/follow-up is still pending, so Conversation Mode can
decide whether to keep listening or return to Sleep.
"""
from __future__ import annotations

import logging
import threading
import time
from typing import Any, Callable

logger = logging.getLogger(__name__)


class CommandResult:
    """Outcome of dispatching one command."""

    __slots__ = ("command", "response", "success", "needs_confirmation", "error")

    def __init__(
        self,
        command: str,
        response: Any = None,
        success: bool = False,
        needs_confirmation: bool = False,
        error: str = "",
    ) -> None:
        self.command = command
        self.response = response
        self.success = success
        self.needs_confirmation = needs_confirmation
        self.error = error

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return (
            f"CommandResult(command={self.command!r}, success={self.success}, "
            f"needs_confirmation={self.needs_confirmation})"
        )


class CommandDispatcher:
    """Runs a command on a worker thread, bounded by a deadline.

    Args:
        runner: Callable ``(text, *, speech_confidence=None) -> response`` — a
            thin adapter over the brain/executor that also records LLM and
            execution timings via ``on_stage_done`` callbacks.
        timeout: Hard deadline (seconds) for a single command.
        on_stage: Optional ``(name, started_at) -> None`` so the caller can
            record structured timings (``llm_ms`` / ``execution_ms``).
    """

    def __init__(
        self,
        runner: Callable[..., Any] | None = None,
        timeout: float = 30.0,
        on_stage: Callable[[str, float], None] | None = None,
    ) -> None:
        self._runner = runner
        self._timeout = float(timeout)
        self._on_stage = on_stage

    def dispatch(self, text: str, confidence: float = 0.0) -> CommandResult:
        """Execute *text* and return a CommandResult (never raises to caller
        on a timeout — it reports ``error`` instead)."""
        if self._runner is None:
            return CommandResult(text, success=False, error="no runner configured")

        start = time.monotonic()
        box: dict[str, Any] = {"result": None, "error": ""}

        def _work() -> None:
            try:
                box["result"] = self._runner(text, speech_confidence=confidence)
                if self._on_stage is not None:
                    self._on_stage("llm_ms", start)
            except Exception as exc:  # pragma: no cover - defensive
                logger.error("CommandDispatcher runner failed: %s", exc, exc_info=True)
                box["error"] = str(exc)

        thread = threading.Thread(target=_work, name="command-worker", daemon=True)
        thread.start()
        thread.join(timeout=self._timeout)

        if thread.is_alive():
            logger.error("CommandDispatcher timed out after %.0fs", self._timeout)
            return CommandResult(text, success=False, error="timeout")

        if box["error"]:
            return CommandResult(text, success=False, error=box["error"])

        response = box["result"]
        if self._on_stage is not None:
            self._on_stage("execution_ms", time.monotonic())
        needs_confirmation = bool(
            getattr(response, "needs_clarification", False)
        )
        success = bool(getattr(response, "success", False))
        return CommandResult(
            text,
            response=response,
            success=success,
            needs_confirmation=needs_confirmation,
        )