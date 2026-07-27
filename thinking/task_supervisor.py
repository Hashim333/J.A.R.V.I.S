from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from models.response import Response


@dataclass(frozen=True)
class TaskStatus:
    intent: str
    status: str
    step_index: int = 0
    total_steps: int = 0
    message: str = ""
    blocking_dialog: dict[str, Any] | None = None
    is_blocked: bool = False


@dataclass(frozen=True)
class SupervisorDecision:
    can_continue: bool
    response: Response | None = None
    details: dict[str, Any] = field(default_factory=dict)


class TaskSupervisor:
    def __init__(
        self,
        task_verifier: Any = None,
    ) -> None:
        self._task_verifier = task_verifier
        self._pending: dict[str, Any] | None = None
        self._current_task: str | None = None
        self._supervised_steps: list[dict[str, Any]] = []

    @property
    def has_pending(self) -> bool:
        if self._pending is not None:
            return True
        if self._task_verifier is not None and hasattr(self._task_verifier, "has_pending"):
            return self._task_verifier.has_pending
        return False

    @property
    def pending_info(self) -> dict[str, Any]:
        if self._pending:
            return self._pending
        if self._task_verifier is not None and hasattr(self._task_verifier, "get_pending_context"):
            return self._task_verifier.get_pending_context()
        return {}

    def start_supervision(self, intent: str, total_steps: int) -> None:
        self._current_task = intent
        self._supervised_steps = []
        self._pending = None

    def check_step(
        self,
        intent: str,
        step_index: int,
        total_steps: int,
        entities: dict[str, Any],
        plan: Any,
    ) -> SupervisorDecision:
        if self._task_verifier is None:
            return SupervisorDecision(can_continue=True)

        if not hasattr(self._task_verifier, "verify"):
            return SupervisorDecision(can_continue=True)

        mock_response = Response(success=True, message="Step completed.")
        result = self._task_verifier.verify(mock_response, intent, entities)

        if result is not mock_response and getattr(result, "needs_clarification", False):
            self._pending = {
                "check_type": "verification_blocked",
                "response": result,
                "intent": intent,
                "entities": entities,
            }
            self._supervised_steps.append({
                "step": step_index,
                "status": "blocked",
                "reason": result.clarification_question,
            })
            return SupervisorDecision(
                can_continue=False,
                response=result,
                details={"blocked": True, "reason": result.clarification_question},
            )

        self._supervised_steps.append({"step": step_index, "status": "completed"})
        return SupervisorDecision(can_continue=True)

    def resolve(self, answer: str) -> Response | None:
        if self._pending is None:
            if self._task_verifier is not None and hasattr(self._task_verifier, "resolve"):
                return self._task_verifier.resolve(answer)
            return None

        pending = self._pending
        check_type = pending.get("check_type", "")
        self._pending = None

        action = answer.strip().casefold()
        if action in ("yes", "ok", "dismiss", "close", "confirm", "continue"):
            return Response(
                success=True,
                message="Continuing.",
                data={"action": "acknowledged"},
            )

        if action in ("retry", "try again"):
            return Response(
                success=True,
                message="Retrying.",
                data={"action": "retry", "intent": pending.get("intent", "")},
            )

        return Response(
            success=True,
            message="Continuing after user input.",
            data={"action": "continue"},
        )

    def end_supervision(self) -> list[dict[str, Any]]:
        steps = self._supervised_steps[:]
        self._current_task = None
        self._supervised_steps = []
        self._pending = None
        return steps
