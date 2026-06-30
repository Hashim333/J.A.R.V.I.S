"""
executor/executor.py

Executor's only job: run an ExecutionPlan by dispatching each Step to
the handler Registry provides, and report what happened as a single
Response.

    Brain -> Parser -> ParsedCommand -> Planner -> ExecutionPlan
        -> Executor -> Registry -> Handler -> Automation Module -> Response

Executor coordinates execution; it does not decide what to execute
(that's Planner's job) and it does not perform automation itself
(that's the Handler/Automation layer's job, reached only through
Registry). Executor never imports automation modules, never calls
pyautogui or subprocess, never parses text, never calls an LLM, and
never builds plans. Its entire responsibility is: for each Step in the
plan, ask Registry for the right handler, call handler.run(step),
collect what happened, and summarize the outcome in one Response.
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from models.execution_plan import ExecutionPlan, Step
from models.response import Response


@runtime_checkable
class Handler(Protocol):
    """
    Structural contract for whatever Registry hands back. Executor
    depends only on this shape -- it never imports a concrete handler
    class (AppsHandler, MouseHandler, KeyboardHandler, ...).
    """

    def run(self, step: Step) -> Any:
        """Execute a single Step and return a result, or raise."""
        ...


@runtime_checkable
class HandlerRegistry(Protocol):
    """
    Structural contract for whatever is passed into Executor's
    constructor. Executor depends only on this shape -- it never
    imports automation.registry or any concrete Registry class, so it
    has no compile-time or import-time dependency on the automation
    package at all.
    """

    def get_handler(self, action: str) -> Handler:
        """Return the handler responsible for the given action."""
        ...


class Executor:
    """
    Runs an ExecutionPlan step by step via a handler registry.

    Constructor:
        Executor(registry) -- registry is any object satisfying the
        HandlerRegistry protocol (i.e. it has a get_handler(action)
        method). Executor stores it as-is; it never constructs,
        configures, or imports a registry itself.

    Public method:
        execute(plan) -> Response
    """

    def __init__(self, registry: HandlerRegistry) -> None:
        self._registry = registry

    def execute(self, plan: ExecutionPlan) -> Response:
        """
        Execute every Step in plan, in order, via the registry's
        handlers.

        For each Step:
            1. Ask the registry for the handler responsible for
               step.action.
            2. Call handler.run(step).
            3. Record whether that step succeeded or failed.

        If every step succeeds, returns a Response with success=True
        summarizing all results. If any step fails (the registry has
        no handler for it, or the handler itself raises), execution
        stops at that step and a Response with success=False is
        returned, describing which step failed and why. Steps already
        completed before the failure are still reported in the
        returned Response's data.

        This method never raises -- any exception encountered while
        resolving or running a handler is caught and converted into a
        failed Response.

        Args:
            plan: the ExecutionPlan to execute.

        Returns:
            A Response summarizing the outcome of the whole plan.
        """
        if not plan.steps:
            return Response(
                success=True,
                message="Execution plan had no steps to run.",
                data={"intent": plan.intent, "results": []},
            )

        results: list[dict[str, Any]] = []

        for index, step in enumerate(plan.steps):
            try:
                handler = self._registry.get_handler(step.action)
            except Exception as exc:  # noqa: BLE001 - intentional, broad by design
                results.append(
                    {
                        "step_index": index,
                        "action": step.action,
                        "success": False,
                        "error": f"{type(exc).__name__}: {exc}",
                    }
                )
                return Response(
                    success=False,
                    message=(
                        f"No handler available for step {index} "
                        f"(action={step.action!r})."
                    ),
                    data={"intent": plan.intent, "results": results},
                    error=f"{type(exc).__name__}: {exc}",
                )

            try:
                result = handler.run(step)
            except Exception as exc:  # noqa: BLE001
                results.append(
                    {
                        "step_index": index,
                        "action": step.action,
                        "success": False,
                        "error": f"{type(exc).__name__}: {exc}",
                    }
                )
                return Response(
                    success=False,
                    message=(
                        f"Step {index} (action={step.action!r}) failed during execution."
                    ),
                    data={"intent": plan.intent, "results": results},
                    error=f"{type(exc).__name__}: {exc}",
                )

            results.append(
                {
                    "step_index": index,
                    "action": step.action,
                    "success": True,
                    "result": result,
                }
            )

        return Response(
            success=True,
            message=f"All {len(results)} step(s) executed successfully.",
            data={"intent": plan.intent, "results": results},
        )