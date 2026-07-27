from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from models.response import Response

if TYPE_CHECKING:
    from verification.task_verifier import TaskVerifier


@dataclass(frozen=True)
class VerificationResult:
    passed: bool
    message: str = ""
    details: dict[str, Any] = field(default_factory=dict)
    needs_retry: bool = False
    retry_response: Response | None = None


class VerificationEngine:
    def __init__(self, task_verifier: TaskVerifier | None = None) -> None:
        self._task_verifier = task_verifier
        self._verification_history: list[dict[str, Any]] = []

    def verify_execution(
        self,
        executor_response: Response,
        intent: str,
        entities: dict[str, Any],
    ) -> VerificationResult:
        self._verification_history.append({
            "intent": intent,
            "executor_success": executor_response.success,
        })

        if not executor_response.success:
            error = executor_response.error or executor_response.message
            return VerificationResult(
                passed=False,
                message=f"Execution failed: {error}",
                details={"executor_error": error},
            )

        if executor_response.needs_clarification:
            return VerificationResult(
                passed=True,
                message="Execution returned a clarification request — handled by pipeline.",
                details={"needs_clarification": True},
            )

        if self._task_verifier is not None:
            verified = self._task_verifier.verify(executor_response, intent, entities)
            if verified is not executor_response and getattr(verified, "needs_clarification", False):
                self._verification_history.append({
                    "intent": intent,
                    "verification": "blocked",
                    "reason": verified.clarification_question,
                })
                return VerificationResult(
                    passed=False,
                    message=f"Verification blocked: {verified.clarification_question}",
                    details={"blocked": True, "verification_response": verified},
                    needs_retry=False,
                    retry_response=verified,
                )
            executor_response = verified

        self._verification_history.append({
            "intent": intent,
            "verification": "passed",
        })
        return VerificationResult(
            passed=True,
            message="Task verified successfully.",
            details={"verified_response": executor_response},
        )

    @property
    def history(self) -> list[dict[str, Any]]:
        return list(self._verification_history)
