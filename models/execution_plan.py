"""
models/execution_plan.py

Defines Step and ExecutionPlan: the canonical, shared representation
of "what should be done," produced by Planner and consumed by
Executor.

    Parser
        |
        v
    ParsedCommand
        |
        v
    Planner.create_plan()
        |
        v
    ExecutionPlan
        |
        v
    Executor.execute()

This file is a pure data model. It defines the shape of a plan and
nothing else -- it does not execute steps, does not decide what a
plan should contain, and does not know Brain, Parser, Planner,
Executor, or automation exist. Planner is responsible for building
instances of these classes; Executor is responsible for interpreting
and acting on them. This file only describes their shape.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class Step:
    """
    A single unit of work within an ExecutionPlan.

    A Step describes *what* should happen, not *how* -- it carries no
    automation logic, no handler references, and no execution code.
    Executor (via Registry and the relevant Handler) is responsible
    for interpreting action/target/parameters and actually performing
    the work; this class only carries that description.

    Attributes:
        action: A short string naming the operation to perform
            (e.g. "open_app", "left_click", "type_text"). This is the
            primary key Executor/Registry use to decide which handler
            should run this step.
        target: The primary subject of the action, if any
            (e.g. "notepad" for an open_app action, or None for an
            action with no single target, like a mouse scroll).
        parameters: Additional keyword-style data the action needs
            beyond its target (e.g. {"x": 100, "y": 200} for a click,
            or {"text": "hello"} for typing). Defaults to an empty
            dict so callers never need a None check.
        description: A short, human-readable explanation of what this
            step does (e.g. "Open the Notepad application"). Intended
            for logging, debugging, and display to the user -- never
            parsed or relied on programmatically.
    """

    action: str
    target: str | None
    parameters: dict[str, Any] = field(default_factory=dict)
    description: str = ""

    def __post_init__(self) -> None:
        """
        Validate field types at construction time.

        Pure data validation only -- no decisions about what the step
        means or how it should run. Exists so a malformed Step fails
        immediately where it's created, rather than deep inside
        Executor.

        Raises:
            TypeError: if action/description are not strings, if
                target is set but not a string, or if parameters is
                not a dict.
        """
        if not isinstance(self.action, str):
            raise TypeError(
                f"action must be a str, got {type(self.action).__name__!r}"
            )
        if self.target is not None and not isinstance(self.target, str):
            raise TypeError(
                f"target must be a str or None, got {type(self.target).__name__!r}"
            )
        if not isinstance(self.parameters, dict):
            raise TypeError(
                f"parameters must be a dict, got {type(self.parameters).__name__!r}"
            )
        if not isinstance(self.description, str):
            raise TypeError(
                f"description must be a str, got {type(self.description).__name__!r}"
            )


@dataclass(frozen=True)
class ExecutionPlan:
    """
    The canonical output of Planner.create_plan() and input to
    Executor.execute().

    An ExecutionPlan is an ordered, immutable sequence of Steps plus
    the intent and confidence that produced it. It carries no
    execution behavior of its own -- it is a description of work to be
    done, not the work being done.

    Attributes:
        intent: The intent this plan was built for (e.g. "open_app",
            "unknown"), carried forward from the ParsedCommand that
            produced it. Lets Executor, logging, or error-handling
            code refer back to the original intent without needing
            the original ParsedCommand.
        confidence: The confidence associated with this plan, on a
            0.0-1.0 scale, carried forward from the ParsedCommand that
            produced it (or otherwise set by Planner). Allows Executor
            or Brain to make decisions (e.g. asking for confirmation
            on low-confidence plans) without re-deriving confidence
            from scratch.
        steps: The ordered list of Step objects to execute, in the
            order they should be performed. Defaults to an empty list
            for plans that result in no actionable work.
        metadata: Any additional, non-essential context Planner wants
            to attach to the plan (e.g. which planning strategy was
            used, timing info, debug notes). Defaults to an empty
            dict. Executor is not required to read this field.
    """

    intent: str
    confidence: float
    steps: list[Step] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        """
        Validate field types and ranges at construction time.

        Pure data validation only -- no decisions about what the plan
        means or how it should be executed. Exists so a malformed
        ExecutionPlan fails immediately where it's created, rather
        than deep inside Executor.

        Raises:
            TypeError: if intent is not a str, if confidence is not a
                float, if steps is not a list (or contains non-Step
                items), or if metadata is not a dict.
            ValueError: if confidence is not within the inclusive
                range [0.0, 1.0].
        """
        if not isinstance(self.intent, str):
            raise TypeError(
                f"intent must be a str, got {type(self.intent).__name__!r}"
            )
        if not isinstance(self.confidence, (int, float)) or isinstance(self.confidence, bool):
            raise TypeError(
                f"confidence must be a float, got {type(self.confidence).__name__!r}"
            )
        if not (0.0 <= float(self.confidence) <= 1.0):
            raise ValueError(
                f"confidence must be between 0.0 and 1.0, got {self.confidence!r}"
            )
        if not isinstance(self.steps, list):
            raise TypeError(
                f"steps must be a list, got {type(self.steps).__name__!r}"
            )
        for index, step in enumerate(self.steps):
            if not isinstance(step, Step):
                raise TypeError(
                    f"steps[{index}] must be a Step, got {type(step).__name__!r}"
                )
        if not isinstance(self.metadata, dict):
            raise TypeError(
                f"metadata must be a dict, got {type(self.metadata).__name__!r}"
            )