from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class DiagnosticReport:
    component: str
    exception: str = ""
    reason: str = ""
    attempted_action: str = ""
    fallback_attempts: list[str] = field(default_factory=list)
    recovery_attempted: str = ""
    recovery_success: bool = False
