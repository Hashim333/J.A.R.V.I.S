"""
brain/planner.py

The Planner converts a ParsedCommand into a step-by-step ExecutionPlan.
"""

from __future__ import annotations

from brain.execution_plan import ExecutionPlan, Step
from brain.parsed_command import ParsedCommand


class Planner:
    """
    A stateless, rule-based planner that maps intents to execution steps.
    """

    def create_plan(self, command: ParsedCommand) -> ExecutionPlan:
        """
        Creates an ExecutionPlan from a ParsedCommand.

        Args:
            command: The structured command from the Parser.

        Returns:
            A step-by-step plan for the Executor.
        """
        builder = self._get_builder(command.intent)
        steps = builder(command)

        return ExecutionPlan(
            raw_text=command.raw_text,
            intent=command.intent,
            confidence=command.confidence,
            steps=steps,
        )

    def _get_builder(self, intent: str) -> callable:
        """Returns the appropriate plan-building method for an intent."""
        return {
            "open_app": self._plan_open_app,
            "close_app": self._plan_close_app,
        }.get(intent, self._plan_unknown)

    def _plan_open_app(self, command: ParsedCommand) -> list[Step]:
        """Builds a plan to open an application."""
        app_name = command.entities.get("app_name")
        if not app_name:
            return []
        return [
            Step(action="open_app", target=app_name, description=f"Open {app_name}.")
        ]

    def _plan_close_app(self, command: ParsedCommand) -> list[Step]:
        """Builds a plan to close an application."""
        app_name = command.entities.get("app_name")
        if not app_name:
            return []
        return [
            Step(action="close_app", target=app_name, description=f"Close {app_name}.")
        ]

    def _plan_unknown(self, command: ParsedCommand) -> list[Step]:
        """Builds an empty plan for an unknown intent."""
        return []