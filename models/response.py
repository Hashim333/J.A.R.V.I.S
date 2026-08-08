"""
models/response.py

The single Response type shared by every layer of the JARVIS pipeline:

    Parser -> (parsed dict)
    Planner.create_plan(parsed) -> Response
    Brain.process(text) -> Response

Every module that returns a result to its caller returns a Response
(or raises, which Brain is responsible for catching and converting
into a Response). No layer invents its own ad-hoc result type.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from models.task_result import TaskResult


@dataclass(frozen=True)
class Response:
    """
    Uniform result object for the pipeline.

    Attributes:
        success: Whether the request was understood and planned successfully.
        message: Human-readable summary, safe to print directly to the user.
        data:    Optional structured payload (e.g. the plan, parsed fields,
                 or any extra context). Defaults to an empty dict so callers
                 can always safely do response.data.get(...) without a
                 None check.
        error:   Error description if success is False, otherwise None.
        task_result: Canonical outcome classification.
        diagnostic:  Structured failure report (None on SUCCESS).
        confidence:  0..1 confidence in the intent/entities that drove
                     this response. ``None`` when not produced by the
                     reasoning layer.
        speech_confidence: 0..1 confidence of the ASR transcript that
                     produced this request. ``None`` for typed input.
        reasoning:   Human-readable trace of why this response was chosen.
    """

    success: bool
    message: str
    data: dict[str, Any] = field(default_factory=dict)
    error: str | None = None
    needs_clarification: bool = False
    clarification_question: str = ""
    alternatives: list[str] = field(default_factory=list)
    task_result: TaskResult = TaskResult.SUCCESS
    diagnostic: Any = None
    confidence: float | None = None
    speech_confidence: float | None = None
    reasoning: str = ""