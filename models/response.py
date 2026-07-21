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
    """

    success: bool
    message: str
    data: dict[str, Any] = field(default_factory=dict)
    error: str | None = None
    needs_clarification: bool = False
    clarification_question: str = ""
    alternatives: list[str] = field(default_factory=list)