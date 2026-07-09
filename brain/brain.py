"""
brain/brain.py

Brain is the single entry point and coordinator of the full pipeline:

    Brain.process(text)
        -> Parser.parse(text)            -> ParsedCommand
        -> Planner.create_plan(parsed)   -> ExecutionPlan
        -> Executor.execute(plan)        -> Response

Brain receives its dependencies (Parser, Planner, Executor) via its
constructor. It does not create them internally. This supports
decoupling and testability.

Brain never touches automation directly and never bypasses Executor.
Once an ExecutionPlan exists, the only thing Brain does with it is
hand it to Executor.execute(plan) and return whatever Response comes
back.
"""

from __future__ import annotations

from brain.parser import Parser
from planner.planner import Planner
from executor.executor import Executor
from models.response import Response


class Brain:
    """
    Coordinates Parser -> Planner -> Executor -> Response.

    Dependencies are injected via the constructor.
    """

    def __init__(
        self, parser: Parser, planner: Planner, executor: Executor
    ) -> None:
        self._parser = parser
        self._planner = planner
        self._executor = executor

    def process(self, text: str) -> Response:
        """
        Run the full pipeline for a single piece of user input.

        Steps:
            1. Parser.parse(text) -> ParsedCommand
            2. Planner.create_plan(parsed) -> ExecutionPlan
            3. Executor.execute(plan) -> Response

        Args:
            text: raw user input.

        Returns:
            A Response. This method never raises -- any exception from
            Parser, Planner, or Executor is caught here and converted
            into a Response with success=False so callers (like
            dev_tests/test_pipeline.py) can print it without crashing.
        """
        try:
            parsed = self._parser.parse(text)
        except Exception as exc:  # noqa: BLE001 - intentional, broad by design
            return Response(
                success=False,
                message="Parser failed while processing input.",
                data={"raw_text": text},
                error=f"{type(exc).__name__}: {exc}",
            )

        try:
            plan = self._planner.create_plan(parsed)
        except Exception as exc:  # noqa: BLE001
            return Response(
                success=False,
                message="Planner failed while creating an execution plan.",
                data={"raw_text": text},
                error=f"{type(exc).__name__}: {exc}",
            )

        try:
            response = self._executor.execute(plan)
        except Exception as exc:  # noqa: BLE001
            return Response(
                success=False,
                message="Executor failed while running the execution plan.",
                data={"raw_text": text, "intent": plan.intent},
                error=f"{type(exc).__name__}: {exc}",
            )

        return response