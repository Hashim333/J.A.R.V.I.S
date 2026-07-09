"""
brain/execution_plan.py

Defines Step and ExecutionPlan, the canonical output of the Planner.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class Step:
    """
    A single, immutable unit of work within an ExecutionPlan.

    Describes *what* should happen, not *how*. It carries no logic.

    Attributes:
        action: The name of the operation (e.g., "open_app").
        target: The primary subject of the action (e.g., "notepad").
        parameters: Additional data for the action.
        description: A human-readable summary of the step.
    """

    action: str
    target: str | None = None
    parameters: dict[str, Any] = field(default_factory=dict)
    description: str = ""


@dataclass(frozen=True)
class ExecutionPlan:
    """
    An immutable, ordered sequence of Steps to be executed.

    This is the final output of the Planner.

    Attributes:
        intent: The user's original intent.
        confidence: The confidence score from the Parser.
        steps: The list of Step objects to be executed.
        raw_text: The original user command for logging/debugging.
    """

    raw_text: str
    intent: str
    confidence: float
    steps: list[Step] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        """Validate field types and ranges at construction time."""
        if not isinstance(self.intent, str):
            raise TypeError(
                f"intent must be a str, got {type(self.intent).__name__!r}"
            )
        if not isinstance(self.confidence, (int, float)) or isinstance(
            self.confidence, bool
        ):
            raise TypeError(
                f"confidence must be a float, got {type(self.confidence).__name__!r}"
            )
        if not 0.0 <= float(self.confidence) <= 1.0:
            raise ValueError(
                f"confidence must be between 0.0 and 1.0, got {self.confidence!r}"
            )
        if not isinstance(self.steps, list):
            raise TypeError(
                f"steps must be a list, got {type(self.steps).__name__!r}"
            )
        if any(not isinstance(s, Step) for s in self.steps):
            raise TypeError("All items in steps must be Step objects.")