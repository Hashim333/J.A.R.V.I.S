"""
brain/time_budget.py — shared nested-LLM time budget (PART 11).

The Brain runs one request under a single wall-clock budget.  Every nested
LLM call (reasoner, utterance classifier) must derive its own timeout from
the same budget so the sum of child calls can never exceed the parent brain
budget — and no request is ever started with a timeout longer than the
parent's remaining time (which previously let an Ollama call keep running in
a discarded daemon worker after the brain had already timed out).
"""
from __future__ import annotations

import time


class TimeBudget:
    """A monotonic deadline shared across nested LLM calls."""

    def __init__(self, seconds: float) -> None:
        self._deadline = time.monotonic() + max(0.0, float(seconds))

    @property
    def remaining(self) -> float:
        return max(0.0, self._deadline - time.monotonic())

    @property
    def expired(self) -> bool:
        return self.remaining <= 0.0

    def child_timeout(self, default: float) -> float:
        """A bounded timeout for one nested call — never larger than the
        parent's remaining time, and never ``default`` once the budget is
        exhausted (so an expired budget aborts immediately)."""
        remaining = self.remaining
        if remaining <= 0.0:
            return 0.0
        return min(max(0.0, float(default)), remaining)
