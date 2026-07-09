"""
brain/planner.py

Planner converts ParsedCommand into ExecutionPlan.

It is pure: no automation calls, no LLM calls, no side effects. New voice
commands become useful by mapping text -> intent in Parser, then intent
-> ordered Step objects here.
"""

from __future__ import annotations

from typing import Any

from brain.execution_plan import ExecutionPlan, Step
from brain.parsed_command import ParsedCommand


class Planner:
    """Converts ParsedCommand -> ExecutionPlan."""

    _DANGEROUS_INTENTS = {
        "shutdown",
        "restart_system",
        "log_out",
        "close_all_app_instances",
        "close_all_windows",
    }

    def create_plan(self, parsed: ParsedCommand) -> ExecutionPlan:
        builder = self._BUILDERS.get(parsed.intent)
        if builder is None:
            steps = self._build_future_action(parsed)
        else:
            steps = builder(self, parsed)

        metadata: dict[str, Any] = {"raw_text": parsed.raw_text}
        if parsed.intent in self._DANGEROUS_INTENTS:
            metadata["requires_confirmation"] = True
            metadata["confirmation_reason"] = (
                f"Intent {parsed.intent!r} is potentially destructive."
            )

        return ExecutionPlan(
            raw_text=parsed.raw_text,
            intent=parsed.intent,
            confidence=parsed.confidence,
            steps=steps,
            metadata=metadata,
        )

    # Application Management: use existing app automation where available.
    def _build_open_app(self, parsed: ParsedCommand) -> list[Step]:
        app_name = parsed.entities.get("app_name")
        return [self._step("open_app", app_name, description=f"Open {app_name}.")]

    def _build_close_app(self, parsed: ParsedCommand) -> list[Step]:
        app = parsed.entities.get("app")
        return [self._step("close_app", app, description=f"Close {app}.")]

    def _build_is_running(self, parsed: ParsedCommand) -> list[Step]:
        app = parsed.entities.get("app")
        return [self._step("is_running", app, description=f"Check whether {app} is running.")]

    def _build_restart_app(self, parsed: ParsedCommand) -> list[Step]:
        app = parsed.entities.get("app")
        return [
            self._step("close_app", app, description=f"Close {app}."),
            self._step("open_app", app, description=f"Open {app}."),
        ]

    def _build_app_window_action(self, parsed: ParsedCommand) -> list[Step]:
        app = parsed.entities.get("app")
        action_by_intent = {
            "focus_app": "focus_window",
            "switch_to_app": "focus_window",
            "minimize_app": "minimize_window",
            "maximize_app": "maximize_window",
            "restore_app": "restore_window",
        }
        action = action_by_intent[parsed.intent]
        return [self._step(action, None, {"title": app}, f"{action.replace('_', ' ').title()} for {app}.")]

    # Browser: produce browser/navigation plans without implementing browser automation here.
    def _build_open_website(self, parsed: ParsedCommand) -> list[Step]:
        url = parsed.entities.get("url")
        return [self._step("navigate", None, {"url": url}, f"Navigate to {url}.")]

    def _build_browser_search(self, parsed: ParsedCommand) -> list[Step]:
        provider = parsed.entities.get("provider")
        query = parsed.entities.get("query")
        return [
            self._step(
                "browser_search", None, {"provider": provider, "query": query}, f"Search {provider} for {query!r}."
            )
        ]

    def _build_browser_action(self, parsed: ParsedCommand) -> list[Step]:
        return [
            self._step(
                parsed.intent,
                None,
                dict(parsed.entities),
                f"Browser action: {parsed.intent.replace('_', ' ')}.",
            )
        ]

    def _build_window_action(self, parsed: ParsedCommand) -> list[Step]:
        return [
            self._step(
                parsed.intent,
                None,
                dict(parsed.entities),
                f"Window action: {parsed.intent.replace('_', ' ')}.",
            )
        ]

    # Keyboard: normalize keyboard intents into currently supported keyboard actions.
    def _build_type_text(self, parsed: ParsedCommand) -> list[Step]:
        text = parsed.entities.get("text", "")
        return [self._step("type_text", None, {"text": text}, f"Type {text!r}.")]

    def _build_press_key(self, parsed: ParsedCommand) -> list[Step]:
        key = parsed.entities.get("key")
        return [self._step("press", None, {"key": key}, f"Press {key}.")]

    def _build_simple_key(self, parsed: ParsedCommand) -> list[Step]:
        action_by_intent = {
            "press_enter": "enter",
            "press_escape": "escape",
            "press_tab": "tab",
            "backspace": "backspace",
            "delete": "press",
        }
        action = action_by_intent[parsed.intent]
        params = {"key": "delete"} if parsed.intent == "delete" else {}
        return [self._step(action, None, params, f"Press {parsed.intent.replace('_', ' ')}.")]

    def _build_hotkey(self, parsed: ParsedCommand) -> list[Step]:
        keys = parsed.entities.get("keys", ())
        return [self._step("hotkey", None, {"keys": keys}, f"Press hotkey {keys}.")]

    def _build_hold_key(self, parsed: ParsedCommand) -> list[Step]:
        key = parsed.entities.get("key")
        return [self._step("hold", None, {"key": key}, f"Hold {key}.")]

    def _build_release_key(self, parsed: ParsedCommand) -> list[Step]:
        key = parsed.entities.get("key")
        return [self._step("release", None, {"key": key}, f"Release {key}.")]

    # Mouse: normalize spoken mouse intents into existing mouse actions.
    def _build_move_mouse(self, parsed: ParsedCommand) -> list[Step]:
        return [self._step("move_mouse", None, dict(parsed.entities), "Move mouse.")]

    def _build_move_relative(self, parsed: ParsedCommand) -> list[Step]:
        return [self._step("move_relative", None, dict(parsed.entities), "Move mouse relatively.")]

    def _build_click(self, parsed: ParsedCommand) -> list[Step]:
        return [self._step(parsed.intent, None, dict(parsed.entities), f"{parsed.intent.replace('_', ' ')}.")]

    def _build_drag_mouse(self, parsed: ParsedCommand) -> list[Step]:
        return [self._step("drag_mouse", None, dict(parsed.entities), "Drag mouse.")]

    def _build_scroll(self, parsed: ParsedCommand) -> list[Step]:
        return [self._step("scroll", None, dict(parsed.entities), "Scroll mouse.")]

    # Safety: dangerous commands intentionally produce no executable steps yet.
    def _build_requires_confirmation(self, parsed: ParsedCommand) -> list[Step]:
        return []

    def _build_unknown(self, parsed: ParsedCommand) -> list[Step]:
        return []

    def _build_future_action(self, parsed: ParsedCommand) -> list[Step]:
        if parsed.intent in self._DANGEROUS_INTENTS:
            return []

        target = parsed.entities.get("target")
        return [
            self._step(
                parsed.intent,
                target if isinstance(target, str) else None,
                dict(parsed.entities),
                f"Planned future action: {parsed.intent.replace('_', ' ')}.",
            )
        ]

    @staticmethod
    def _step(
        action: str,
        target: object,
        parameters: dict[str, Any] | None = None,
        description: str = "",
    ) -> Step:
        return Step(
            action=action,
            target=target if isinstance(target, str) else None,
            parameters=parameters or {},
            description=description,
        )

    _BUILDERS: dict[str, Any] = {
        "open_app": _build_open_app,
        "close_app": _build_close_app,
        "is_running": _build_is_running,
        "restart_app": _build_restart_app,
        "focus_app": _build_app_window_action,
        "switch_to_app": _build_app_window_action,
        "minimize_app": _build_app_window_action,
        "maximize_app": _build_app_window_action,
        "restore_app": _build_app_window_action,
        "close_all_app_instances": _build_requires_confirmation,
        "open_website": _build_open_website,
        "browser_search": _build_browser_search,
        "new_tab": _build_browser_action,
        "close_current_tab": _build_browser_action,
        "close_specific_tab": _build_browser_action,
        "close_all_tabs": _build_browser_action,
        "close_other_tabs": _build_browser_action,
        "switch_tab": _build_browser_action,
        "active_window": _build_window_action,
        "list_windows": _build_window_action,
        "focus_window": _build_app_window_action,
        "duplicate_tab": _build_browser_action,
        "reload": _build_browser_action,
        "back": _build_browser_action,
        "forward": _build_browser_action,
        "type_text": _build_type_text,
        "press_key": _build_press_key,
        "press_enter": _build_simple_key,
        "press_escape": _build_simple_key,
        "press_tab": _build_simple_key,
        "backspace": _build_simple_key,
        "delete": _build_simple_key,
        "hotkey": _build_hotkey,
        "hold_key": _build_hold_key,
        "release_key": _build_release_key,
        "move_mouse": _build_move_mouse,
        "move_relative": _build_move_relative,
        "left_click": _build_click,
        "right_click": _build_click,
        "double_click": _build_click,
        "drag_mouse": _build_drag_mouse,
        "scroll_up": _build_scroll,
        "scroll_down": _build_scroll,
        "shutdown": _build_requires_confirmation,
        "restart_system": _build_requires_confirmation,
        "log_out": _build_requires_confirmation,
        "close_all_windows": _build_requires_confirmation,
        "unknown": _build_unknown,
    }
