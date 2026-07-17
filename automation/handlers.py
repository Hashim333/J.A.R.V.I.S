"""
automation/handlers.py

Adapter layer between Executor and the automation modules.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import automation.apps as apps
import automation.browser as browser
import automation.windows as windows
from automation.keyboard import KeyboardController
from automation.mouse import MouseController
from models.execution_plan import Step


class UnsupportedActionError(Exception):
    """Raised when a handler receives an action it does not support."""

    def __init__(self, handler_name: str, action: str, supported: set[str]) -> None:
        super().__init__(
            f"{handler_name} does not support action {action!r}. "
            f"Supported actions: {sorted(supported)!r}"
        )


class StepParameterError(ValueError):
    """Raised when a Step is missing parameters required by its action."""


def _require_target(step: Step) -> str:
    if not isinstance(step.target, str) or not step.target.strip():
        raise StepParameterError(f"Step action {step.action!r} requires a target.")
    return step.target


def _require_parameter(step: Step, name: str) -> Any:
    try:
        return step.parameters[name]
    except KeyError:
        raise StepParameterError(
            f"Step action {step.action!r} requires parameter {name!r}."
        ) from None


class AppsHandler:
    """Adapter for application-level actions in automation.apps."""

    _SUPPORTED_ACTIONS = {"open_app", "close_app", "is_running"}

    def run(self, step: Step, voice_input: Callable[[], str | None] | None = None) -> Any:
        if step.action == "open_app":
            profile = step.parameters.get("profile")
            return apps.open_app(
                _require_target(step),
                voice_input=voice_input,
                profile=profile,
            )

        if step.action == "close_app":
            return apps.close_app(_require_target(step))

        if step.action == "is_running":
            return apps.is_running(_require_target(step))

        raise UnsupportedActionError(
            handler_name="AppsHandler",
            action=step.action,
            supported=self._SUPPORTED_ACTIONS,
        )


class WindowHandler:
    """Adapter for window management actions."""

    _SUPPORTED_ACTIONS = {
        "active_window",
        "list_windows",
        "focus_window",
    }

    def run(self, step: Step, **kwargs: Any) -> Any:
        if step.action == "active_window":
            return windows.get_active_window()

        if step.action == "list_windows":
            return windows.list_windows()

        if step.action == "focus_window":
            title = _require_parameter(step, "title")
            return windows.focus_window(title)

        raise UnsupportedActionError(
            handler_name="WindowHandler",
            action=step.action,
            supported=self._SUPPORTED_ACTIONS,
        )


class BrowserHandler:
    """Adapter for default-browser navigation actions."""

    _SUPPORTED_ACTIONS = {
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
        "reload",
    }

    def run(self, step: Step, **kwargs: Any) -> Any:
        if step.action == "navigate":
            url = step.parameters.get("url") or step.target
            if not isinstance(url, str) or not url.strip():
                raise StepParameterError(
                    "Step action 'navigate' requires a non-empty 'url' parameter "
                    "or target."
                )
            return browser.open_url(url)

        if step.action == "browser_search":
            provider = _require_parameter(step, "provider")
            query = _require_parameter(step, "query")
            return browser.search(provider, query)
        
        if step.action == "new_tab":
            return browser.new_tab()
        if step.action == "close_current_tab":
            return browser.close_current_tab()
        if step.action == "close_all_tabs":
            return browser.close_all_tabs()
        if step.action == "next_tab":
            return browser.next_tab()
        if step.action == "previous_tab":
            return browser.previous_tab()
        if step.action == "duplicate_tab":
            return browser.duplicate_tab()
        if step.action == "reopen_closed_tab":
            return browser.reopen_closed_tab()
        if step.action == "refresh_page":
            return browser.refresh_page(hard=False)
        if step.action == "hard_refresh":
            return browser.refresh_page(hard=True)
        if step.action == "reload":
            return browser.reload()

        raise UnsupportedActionError(
            handler_name="BrowserHandler",
            action=step.action,
            supported=self._SUPPORTED_ACTIONS,
        )


class MouseHandler:
    """Adapter for mouse actions backed by MouseController."""

    _SUPPORTED_ACTIONS = {
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
    }

    def __init__(self) -> None:
        self._controller = MouseController()

    def run(self, step: Step, **kwargs: Any) -> Any:
        if step.action in {"move", "move_mouse"}:
            return self._controller.move_to(
                _require_parameter(step, "x"),
                _require_parameter(step, "y"),
                duration=step.parameters.get("duration", 0.2),
            )

        if step.action in {"relative_move", "move_relative"}:
            return self._controller.move_relative(
                _require_parameter(step, "dx"),
                _require_parameter(step, "dy"),
                duration=step.parameters.get("duration", 0.2),
            )

        if step.action == "left_click":
            self._move_if_coordinates_are_present(step)
            return self._controller.left_click()

        if step.action == "right_click":
            self._move_if_coordinates_are_present(step)
            return self._controller.right_click()

        if step.action == "double_click":
            self._move_if_coordinates_are_present(step)
            return self._controller.double_click()

        if step.action in {"drag", "drag_mouse", "drag_to"}:
            return self._controller.drag_to(
                _require_parameter(step, "x"),
                _require_parameter(step, "y"),
                duration=step.parameters.get("duration", 0.5),
            )

        if step.action == "scroll":
            return self._controller.scroll(_require_parameter(step, "amount"))

        raise UnsupportedActionError(
            handler_name="MouseHandler",
            action=step.action,
            supported=self._SUPPORTED_ACTIONS,
        )

    def _move_if_coordinates_are_present(self, step: Step) -> None:
        has_x = "x" in step.parameters
        has_y = "y" in step.parameters
        if not has_x and not has_y:
            return
        if has_x != has_y:
            raise StepParameterError(
                f"Step action {step.action!r} must provide both 'x' and 'y'."
            )

        moved = self._controller.move_to(
            step.parameters["x"],
            step.parameters["y"],
            duration=step.parameters.get("duration", 0.2),
        )
        if not moved:
            raise RuntimeError(
                f"Could not move mouse to ({step.parameters['x']}, {step.parameters['y']})."
            )


class KeyboardHandler:
    """Adapter for keyboard actions backed by KeyboardController."""

    _SUPPORTED_ACTIONS = {
        "type_text",
        "press",
        "hotkey",
        "hold",
        "release",
        "enter",
        "escape",
        "tab",
        "backspace",
    }

    def __init__(self) -> None:
        self._controller = KeyboardController()

    def run(self, step: Step, **kwargs: Any) -> Any:
        if step.action == "type_text":
            return self._controller.type_text(_require_parameter(step, "text"))

        if step.action == "press":
            return self._controller.press(_require_parameter(step, "key"))

        if step.action == "hotkey":
            keys = _require_parameter(step, "keys")
            if isinstance(keys, str):
                return self._controller.hotkey(keys)
            if isinstance(keys, (list, tuple)):
                return self._controller.hotkey(*keys)
            raise StepParameterError(
                "Step action 'hotkey' requires 'keys' to be a string, list, or tuple."
            )

        if step.action == "hold":
            return self._controller.hold(_require_parameter(step, "key"))

        if step.action == "release":
            return self._controller.release(_require_parameter(step, "key"))

        if step.action == "enter":
            return self._controller.enter()

        if step.action == "escape":
            return self._controller.escape()

        if step.action == "tab":
            return self._controller.tab()

        if step.action == "backspace":
            return self._controller.backspace()

        raise UnsupportedActionError(
            handler_name="KeyboardHandler",
            action=step.action,
            supported=self._SUPPORTED_ACTIONS,
        )
