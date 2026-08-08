"""
models/action_result.py

ActionResult — the typed contract for a single action execution.

Historically the Executor let handlers return whatever they liked
(``bool`` or ad-hoc ``dict`` results), and the Executor itself invented
its own local ``Response`` type. ``ActionResult`` replaces that ad-hoc
contract: every handler result is normalized into an ``ActionResult``
and ``Executor.execute()`` returns one.

It mirrors the fields of ``models/response.py:Response`` so nothing is
lost at the executor boundary and downstream layers (ResponseGenerator,
VerificationEngine, Brain) can consume it unchanged.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from models.task_result import TaskResult

_RESERVED_KEYS = frozenset({
    "success", "message", "error",
    "needs_clarification", "clarification_question",
    "status",
})

# Handler `status` string → TaskResult mapping. Handlers may report a
# transient execution state instead of a binary success/failure:
#   "retrying" / "retry"          → RETRYING  (a step failed and will retry)
#   "waiting" / "wait"            → WAITING   (awaiting an external condition)
#   "user_confirmation"/"confirm" → USER_CONFIRMATION (asks the user)
_STATUS_MAP: dict[str, TaskResult] = {
    "retrying": TaskResult.RETRYING,
    "retry": TaskResult.RETRYING,
    "waiting": TaskResult.WAITING,
    "wait": TaskResult.WAITING,
    "user_confirmation": TaskResult.USER_CONFIRMATION,
    "confirm": TaskResult.USER_CONFIRMATION,
    "success": TaskResult.SUCCESS,
    "ok": TaskResult.SUCCESS,
    "done": TaskResult.SUCCESS,
    "failed": TaskResult.FAILED,
    "error": TaskResult.FAILED,
}


@dataclass(frozen=True)
class ActionResult:
    """Structured outcome of executing a single action (or plan)."""

    success: bool
    message: str
    data: dict[str, Any] = field(default_factory=dict)
    error: str | None = None
    needs_clarification: bool = False
    clarification_question: str = ""
    task_result: TaskResult = TaskResult.SUCCESS
    verification: dict[str, Any] | None = None
    duration_ms: float | None = None
    retry_count: int = 0

    @classmethod
    def from_handler(
        cls,
        result: Any,
        fallback_message: str = "Action completed.",
    ) -> "ActionResult":
        """Normalize a handler return value into an ``ActionResult``.

        Accepts ``ActionResult`` (returned unchanged), a dict (the
        existing handler convention of ``{"success": bool, ...}``), or a
        plain bool. Anything else is treated as a failure so a
        misbehaving handler can never be mistaken for success.

        Non-reserved dict keys are preserved in ``data``.
        """
        if isinstance(result, cls):
            return result

        if isinstance(result, bool):
            return cls(
                success=result,
                message=fallback_message if result else "Action failed.",
                error=None if result else "Handler returned False.",
                task_result=TaskResult.SUCCESS if result else TaskResult.FAILED,
            )

        if isinstance(result, dict):
            success = bool(result.get("success", True))
            needs_clarification = bool(result.get("needs_clarification", False))
            status = str(result.get("status", "")).casefold()
            extra = {
                k: v for k, v in result.items() if k not in _RESERVED_KEYS
            }

            if needs_clarification:
                task_result = TaskResult.CLARIFICATION
            elif status in _STATUS_MAP:
                task_result = _STATUS_MAP[status]
            else:
                task_result = TaskResult.SUCCESS if success else TaskResult.FAILED

            message = str(result.get("message", fallback_message))
            reason = str(result.get("reason") or result.get("error") or "")
            recovery = str(result.get("recovery") or "")
            if not message or message.casefold() in {"action failed.", "failed.", "done.", "action completed."}:
                if reason:
                    message = reason if not recovery else f"{reason} {recovery}".strip()
                else:
                    message = fallback_message if success else "Action failed."

            return cls(
                success=success,
                message=message,
                data=extra,
                error=result.get("error"),
                needs_clarification=needs_clarification,
                clarification_question=str(
                    result.get("clarification_question", "") or ""
                ),
                task_result=task_result,
            )

        return cls(
            success=False,
            message=fallback_message,
            error=f"Handler returned unexpected type: {type(result).__name__}",
            task_result=TaskResult.INTERNAL_ERROR,
        )
