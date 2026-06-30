"""
brain package public API.

Exposes:
    Brain -- the single coordinator class that drives the full pipeline
             (Parser -> Planner -> Executor -> Registry -> Automation).

This lets the rest of JARVIS (and tests) do:

    from brain import Brain

instead of reaching into the internal module path:

    from brain.brain import Brain
"""

from __future__ import annotations

from .brain import Brain

__all__ = ["Brain"]