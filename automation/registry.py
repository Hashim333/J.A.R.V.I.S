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
            FileManagerHandler,
            KeyboardHandler,
            MouseHandler,
            SecurityToolsHandler,
            VisionHandler,
            WindowHandler,
            SpecialFolderHandler,
            SettingsHandler,
            VolumeHandler,
            ScreenshotHandler,
            SystemHandler,
        )

        apps_handler = AppsHandler()
        browser_handler = BrowserHandler()
        mouse_handler = MouseHandler()
        keyboard_handler = KeyboardHandler()
        window_handler = WindowHandler()
        folder_handler = SpecialFolderHandler()
        settings_handler = SettingsHandler()
        volume_handler = VolumeHandler()
        screenshot_handler = ScreenshotHandler()
        system_handler = SystemHandler()
        file_manager_handler = FileManagerHandler()
        security_handler = SecurityToolsHandler()
        vision_handler = VisionHandler()

        # Apps: open, close, focus, restart, minimize, maximize, restore, close_all, is_running
        for action in ("open_app", "close_app", "focus_app", "restart_app",
                       "minimize_app", "maximize_app", "restore_app",
                       "close_all_apps", "is_running"):
            self.register(action, apps_handler)

        # Browser
        for action in (
            "navigate",
            "browser_search",
            "open_website",
            "search",
            "new_tab",
            "close_current_tab",
            "close_specific_tab",
            "close_all_tabs",
            "close_other_tabs",
            "switch_tab",
            "next_tab",
            "previous_tab",
            "duplicate_tab",
            "reopen_closed_tab",
            "refresh_page",
            "hard_refresh",
            "reload",
            "back",
            "forward",
        ):
            self.register(action, browser_handler)

        # Mouse
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

        # Keyboard
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

        # Window management
        for action in (
            "active_window",
            "list_windows",
            "focus_window",
            "minimize_window",
            "maximize_window",
            "restore_window",
        ):
            self.register(action, window_handler)

        # Special folders
        self.register("open_special_folder", folder_handler)

        # Settings
        self.register("open_settings", settings_handler)

        # Volume
        for action in (
            "increase_volume",
            "decrease_volume",
            "set_volume",
            "mute_volume",
            "unmute_volume",
        ):
            self.register(action, volume_handler)

        # Screenshot
        self.register("screenshot", screenshot_handler)

        # File management
        for action in (
            "open_file",
            "find_file",
            "open_file_location",
            "copy_file",
            "move_file",
            "rename_file",
            "delete_file",
        ):
            self.register(action, file_manager_handler)

        # Security / pentest tooling
        for action in (
            "create_pentest_report",
            "organize_scan_results",
            "summarize_scan_results",
            "create_pentest_project",
        ):
            self.register(action, security_handler)

        # Vision / screen understanding
        for action in (
            "read_screen",
            "describe_screen",
            "click_element",
            "find_element",
            "read_pdf",
            "ocr_image",
            "read_error",
            "fill_form",
        ):
            self.register(action, vision_handler)

        # System commands
        for action in (
            "lock", "shutdown", "restart", "sleep",
            "set_brightness", "wifi_on", "wifi_off",
            "bluetooth_on", "bluetooth_off",
            "airplane_mode_on", "airplane_mode_off",
            "system_status", "sign_out", "cancel_shutdown",
            "open_task_manager", "open_device_manager", "open_control_panel",
            "format_drive", "kill_process",
        ):
            self.register(action, system_handler)

    @staticmethod
    def _validate_action(action: str) -> None:
        if not isinstance(action, str):
            raise TypeError(
                f"Registry action must be a string; got {type(action).__name__!r}."
            )
        if not action.strip():
            raise ValueError("Registry action must not be empty.")
