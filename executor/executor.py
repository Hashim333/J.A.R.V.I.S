"""
executor/executor.py

The Executor runs an ExecutionPlan by dispatching each Step to a handler
provided by a Registry.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from brain.execution_plan import ExecutionPlan, Step
from executor.registry import Registry


@dataclass(frozen=True)
class Response:
    """A structured summary of an execution attempt."""

    success: bool
    message: str
    data: dict[str, Any] = field(default_factory=dict)
    error: str | None = None


class Executor:
    """
    Runs an ExecutionPlan step by step via a handler registry.
    """

    def __init__(
        self,
        registry: Registry,
        voice_input: Callable[[], str | None] | None = None,
    ) -> None:
        self._registry = registry
        self._voice_input = voice_input

    def execute(self, plan: ExecutionPlan) -> Response:
        """
        Execute every Step in a plan, in order.

        If any step fails, execution stops immediately and a failure
        Response is returned.
        """
        if not plan.steps:
            return Response(
                success=True,
                message="Execution plan had no steps to run.",
            )

        results: list[dict[str, Any]] = []

        for index, step in enumerate(plan.steps):
            try:
                handler = self._registry.get_handler(step.action)
                result = handler.run(step, voice_input=self._voice_input)

                results.append(
                    {
                        "step_index": index,
                        "action": step.action,
                        "success": True,
                        "result": result,
                    }
                )

            except Exception as exc:
                if isinstance(exc, KeyError) and exc.args:
                    error_message = f"KeyError: '{exc.args[0]}'"
                else:
                    error_message = f"{type(exc).__name__}: {exc}"

                return Response(
                    success=False,
                    message=f"Step {index} (action={step.action!r}) failed.",
                    data={
                        "intent": plan.intent,
                        "results": results,
                    },
                    error=error_message,
                )

        return Response(
            success=True,
            message=f"All {len(results)} step(s) executed successfully.",
            data={
                "intent": plan.intent,
                "results": results,
            },
        )