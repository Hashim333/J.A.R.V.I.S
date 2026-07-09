"""
executor/registry.py

Registry maps action strings to handler instances.
"""

from __future__ import annotations

from typing import Any


class Registry:
    """Stores and retrieves handlers by their registered action string."""

    def __init__(self) -> None:
        
        self._handlers: dict[str, Any] = {}

    def register(self, action: str, handler: Any) -> None:
        """
        Register a handler instance for a given action string.

        If an action is registered twice, the new handler replaces the old one.
        """
        if not isinstance(action, str) or not action.strip():
            raise ValueError("Registry action must be a non-empty string.")
        self._handlers[action] = handler

    def get_handler(self, action: str) -> Any:
        """
        Return the handler registered for an action string.

        Raises:
            KeyError: if no handler is registered for the action.
        """
        try:
            return self._handlers[action]
        except KeyError:
            raise KeyError(f"No handler registered for action: {action!r}") from None