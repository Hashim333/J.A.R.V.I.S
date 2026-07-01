"""
automation/registry.py

Registry maps action strings to handler instances.

It stores and returns handlers only. Executor remains responsible for
calling handler.run(step).
"""

from __future__ import annotations

from typing import Any


class Registry:
    """Store and retrieve handlers by action string."""

    __slots__ = ("_handlers",)

    def __init__(self) -> None:
        self._handlers: dict[str, Any] = {}
        self._register_default_handlers()

    def register(self, action: str, handler: Any) -> None:
        """Register a handler instance for an action string."""
        self._validate_action(action)
        self._handlers[action] = handler

    def get_handler(self, action: str) -> Any:
        """Return the handler registered for an action string."""
        self._validate_action(action)

        try:
            return self._handlers[action]
        except KeyError:
            raise KeyError(f"No handler registered for action: {action!r}") from None

    def is_registered(self, action: str) -> bool:
        """Return True when an action has a registered handler."""
        self._validate_action(action)
        return action in self._handlers

    def registered_actions(self) -> frozenset[str]:
        """Return every registered action string."""
        return frozenset(self._handlers)

    def _register_default_handlers(self) -> None:
        from automation.handlers import (
            AppsHandler,
            BrowserHandler,
            KeyboardHandler,
            MouseHandler,
        )

        apps_handler = AppsHandler()
        browser_handler = BrowserHandler()
        mouse_handler = MouseHandler()
        keyboard_handler = KeyboardHandler()

        for action in ("open_app", "close_app", "is_running"):
            self.register(action, apps_handler)

        for action in (
            "navigate",
            "browser_search",
            "new_tab",
            "close_current_tab",
            "close_all_tabs",
            "next_tab",
            "previous_tab",
            "duplicate_tab",
            "reopen_closed_tab",
            "refresh_page",
            "hard_refresh",
        ):
            self.register(action, browser_handler)

        for action in (
            "move",
            "move_mouse",
            "relative_move",
            "move_relative",
            "left_click",
            "right_click",
            "double_click",
            "drag",
            "drag_mouse",
            "drag_to",
            "scroll",
        ):
            self.register(action, mouse_handler)

        for action in (
            "type_text",
            "press",
            "hotkey",
            "hold",
            "release",
            "enter",
            "escape",
            "tab",
            "backspace",
        ):
            self.register(action, keyboard_handler)

    @staticmethod
    def _validate_action(action: str) -> None:
        if not isinstance(action, str):
            raise TypeError(
                f"Registry action must be a string; got {type(action).__name__!r}."
            )
        if not action.strip():
            raise ValueError("Registry action must not be empty.")
