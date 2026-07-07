"""
brain/parsed_command.py

Defines ParsedCommand, the immutable data model produced by Parser.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class ParsedCommand:
    """Structured representation of a parsed user command."""

    raw_text: str
    intent: str
    confidence: float = 1.0
    entities: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.raw_text, str):
            raise TypeError(
                f"raw_text must be a str, got {type(self.raw_text).__name__!r}"
            )

        if not isinstance(self.intent, str) or not self.intent:
            raise ValueError("intent must be a non-empty str.")

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

        if not isinstance(self.entities, dict):
            raise TypeError(
                f"entities must be a dict, got {type(self.entities).__name__!r}"
            )