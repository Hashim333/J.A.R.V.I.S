"""
automation/handlers.py

Adapter layer between Executor and the automation modules.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from typing import Any

import psutil

import automation.apps as apps
import automation.browser as browser
import automation.file_ops as file_ops
import automation.interactive_launcher as interactive
import automation.security_tools as security_tools
import automation.system_ops as system_ops
import automation.windows as windows
from automation.application_registry import ApplicationRegistry, _GENERIC_ALIASES
from memory.file_memory import FileMemory
from automation.keyboard import KeyboardController
from automation.mouse import MouseController
from models.execution_plan import Step

logger = logging.getLogger(__name__)


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
    """Adapter for application-level actions using dynamic ApplicationRegistry.

    Supports: open, close, focus, restart, minimize, maximize, restore,
    close_all_apps, is_running.
    """

    _SUPPORTED_ACTIONS = {
        "open_app", "close_app", "focus_app", "restart_app",
        "minimize_app", "maximize_app", "restore_app",
        "close_all_apps", "is_running",
    }

    def __init__(self) -> None:
        self._app_registry = ApplicationRegistry()

    def run(self, step: Step, voice_input: Callable[[], str | None] | None = None) -> Any:
        target = _require_target(step) if step.action != "close_all_apps" else ""

        if step.action == "open_app":
            return self._open_app(target, step, voice_input)
        if step.action == "close_app":
            return self._close_app(target, voice_input)
        if step.action == "focus_app":
            return self._focus_app(target)
        if step.action == "restart_app":
            return self._restart_app(target)
        if step.action == "minimize_app":
            return self._minimize_app(target)
        if step.action == "maximize_app":
            return self._maximize_app(target)
        if step.action == "restore_app":
            return self._restore_app(target)
        if step.action == "close_all_apps":
            return self._close_all_apps()
        if step.action == "is_running":
            return apps.is_running(target)

        raise UnsupportedActionError(
            handler_name="AppsHandler",
            action=step.action,
            supported=self._SUPPORTED_ACTIONS,
        )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _resolve_app(self, target: str) -> Any | None:
        """Look up an app by name, handling ambiguity and generic aliases.
        
        Returns ApplicationInfo on success, dict with needs_clarification on
        ambiguity, or None when not found (including well-known stubs with no
        executable).
        """
        logger.info("Looking up app: %s", target)
        app_info = self._app_registry.lookup(target)
        if app_info is not None:
            if not app_info.executable:
                logger.info("App %r matched stub %s (not installed)", target, app_info.canonical_name)
                return None
            logger.info("Resolved %r -> %s (exe=%s)", target, app_info.canonical_name, app_info.executable)
            return app_info

        matches = self._app_registry.search(target, threshold=0.3)
        if len(matches) >= 2:
            names = [m[0].canonical_name for m in matches[:3]]
            logger.info("Multiple matches for %r: %s", target, names)
            return {"needs_clarification": True, "names": names, "matches": [m[0] for m in matches[:5]]}

        generic = _GENERIC_ALIASES.get(target.strip().casefold())
        if generic:
            app_info = self._app_registry.lookup(generic)
            if app_info:
                logger.info("Generic alias %r -> %r -> %s", target, generic, app_info.canonical_name)
                return app_info

        logger.info("App not found: %s", target)
        return None

    def _app_not_found(self, target: str) -> dict:
        return {"success": False, "message": f"I couldn't find {target!r} installed."}

    def _not_running_msg(self, canonical: str) -> dict:
        return {"success": True, "message": f"{canonical} is not running.", "details": {"action": "none_needed"}}

    def _success_msg(self, canonical: str, action: str) -> dict:
        verb_map = {"launched": "opened", "closed": "closed", "focused": "focused",
                     "restarted": "restarted", "minimized": "minimized", "maximized": "maximized",
                     "restored": "restored", "force_closed": "force closed"}
        verb = verb_map.get(action, action)
        return {"success": True, "message": f"{canonical} {verb}.", "details": {"action": action, "app": canonical}}

    # ------------------------------------------------------------------
    # Open app
    # ------------------------------------------------------------------

    def _open_app(
        self,
        target: str,
        step: Step,
        voice_input: Callable[[], str | None] | None,
    ) -> dict:
        app_info = self._resolve_app(target)
        if app_info is None:
            return self._app_not_found(target)
        if isinstance(app_info, dict) and app_info.get("needs_clarification"):
            names = app_info["names"]
            msg = f"Did you mean: {', '.join(names)}?"
            return {"success": False, "needs_clarification": True, "clarification_question": msg, "message": msg, "matches": app_info["matches"]}

        process_name = app_info.process_name
        focus_if_running = step.parameters.get("focus_if_running", True)
        if focus_if_running and apps.is_process_running(process_name):
            focus_result = apps.focus_process(process_name)
            if focus_result["success"]:
                logger.info("Intent=OPEN_APPLICATION App=%s Action=focus_existing PID=window Success=True", app_info.canonical_name)
                return self._success_msg(app_info.canonical_name, "focused")
            logger.info("Intent=OPEN_APPLICATION App=%s Action=already_running PID=window Success=True", app_info.canonical_name)
            return {"success": True, "message": f"{app_info.canonical_name} is already running.", "details": {"action": "already_running", "app": app_info.canonical_name}}

        extra_args: list[str] = []
        profile = step.parameters.get("profile")
        if profile and "chrome" in app_info.canonical_name.casefold():
            extra_args = [f"--profile-directory={profile}"]

        result = apps.launch_executable(app_info.executable, extra_args, process_name)
        logger.info("Intent=OPEN_APPLICATION App=%s Matched=%s Executable=%s LaunchMethod=%s Success=%s",
                     target, app_info.canonical_name, app_info.executable, app_info.launch_method, result["success"])
        if not result["success"]:
            return result

        # Check for interactive dialogs (Chrome profile picker, launcher dialogs, etc.)
        interactive_result = interactive.handle_interactive_launch(
            app_name=app_info.canonical_name,
            process_name=process_name,
            voice_input=voice_input,
            profile=profile,
        )
        if interactive_result is not None:
            logger.info("Intent=OPEN_APPLICATION App=%s Action=interactive Handled=%s",
                         app_info.canonical_name, interactive_result.get("success"))
            return interactive_result

        launched = apps.verify_launch_by_process(process_name)
        if launched:
            pids = [str(p.info["pid"]) for p in psutil.process_iter(["name", "pid"]) if p.info.get("name", "").casefold() == process_name.casefold()]
            logger.info("Intent=OPEN_APPLICATION App=%s Action=launched PID=%s Success=True", app_info.canonical_name, ",".join(pids[:3]))
            return self._success_msg(app_info.canonical_name, "launched")

        logger.warning("Intent=OPEN_APPLICATION App=%s Action=verify_launch Success=False", app_info.canonical_name)
        return {"success": False, "message": f"{app_info.canonical_name} could not be verified as running after launch.", "details": {"app": app_info.canonical_name}}

    # ------------------------------------------------------------------
    # Close app
    # ------------------------------------------------------------------

    def _close_app(
        self,
        target: str,
        voice_input: Callable[[], str | None] | None = None,
        auto_force: bool = True,
    ) -> dict:
        app_info = self._resolve_app(target)
        if app_info is None:
            return self._app_not_found(target)
        if isinstance(app_info, dict) and app_info.get("needs_clarification"):
            names = app_info["names"]
            return {"success": False, "message": f"Did you mean: {', '.join(names)}?"}

        process_name = app_info.process_name
        executable = app_info.executable or "unknown"

        if not apps.is_process_running(process_name):
            logger.info("Intent=CLOSE_APPLICATION App=%s Action=none_needed Success=True", app_info.canonical_name)
            return self._not_running_msg(app_info.canonical_name)

        # Collect target process info for logging
        pids = sorted(apps.collect_process_pids(process_name))
        windows = apps.find_windows_for_process(process_name)

        # Detailed pre-close logging
        logger.info(
            "Intent=CLOSE_APPLICATION App=%s Matched=%s Executable=%s PIDs=%s Windows=%d",
            target, app_info.canonical_name, executable, pids, len(windows),
        )
        for win in windows:
            logger.info(
                "Intent=CLOSE_APPLICATION App=%s PID=%d HWND=%d Title=%s",
                app_info.canonical_name, win["pid"], win["hwnd"], win["title"] or "(untitled)",
            )

        # Handle multiple instances
        close_active_only = False
        if len(windows) > 1:
            choice = self._prompt_multiple_instances(
                app_info.canonical_name, len(windows), voice_input,
            )
            if choice == "cancel":
                logger.info("Intent=CLOSE_APPLICATION App=%s Action=cancelled_by_user", app_info.canonical_name)
                return {"success": False, "message": f"Cancelled closing {app_info.canonical_name}."}
            close_active_only = (choice == "active")

        # Graceful close
        if close_active_only:
            result = self._close_active_window(process_name, app_info.canonical_name)
            if result.get("success"):
                return result
            # Fall through to close all if active-only failed
        result = apps.close_process(process_name, display_name=app_info.canonical_name)
        if result.get("success"):
            logger.info(
                "Intent=CLOSE_APPLICATION App=%s Action=graceful PIDs=%s Success=True",
                app_info.canonical_name, pids,
            )
            return self._success_msg(app_info.canonical_name, "closed")

        # Graceful failed — force close (only target process)
        if auto_force or result.get("needs_force_close"):
            logger.info(
                "Intent=CLOSE_APPLICATION App=%s Action=force PIDs=%s",
                app_info.canonical_name, pids,
            )
            force_result = apps.force_process_kill(process_name)
            if force_result["success"]:
                logger.info(
                    "Intent=CLOSE_APPLICATION App=%s Action=force PIDs=%s Success=True",
                    app_info.canonical_name, pids,
                )
                return self._success_msg(app_info.canonical_name, "force_closed")
            logger.warning(
                "Intent=CLOSE_APPLICATION App=%s Action=force PIDs=%s Success=False",
                app_info.canonical_name, pids,
            )

        logger.warning(
            "Intent=CLOSE_APPLICATION App=%s Action=close_process PIDs=%s Success=False",
            app_info.canonical_name, pids,
        )
        return {"success": False, "message": f"Failed to close {app_info.canonical_name}. The process is still running.", "details": {"app": app_info.canonical_name}}

    def _close_active_window(self, process_name: str, canonical: str) -> dict:
        """Close only the active/foreground window belonging to *process_name*."""
        try:
            import pygetwindow as gw
            active = gw.getActiveWindow()
            if active is None:
                return {"success": False, "message": f"No active window found for {canonical}."}
            hwnd = active._hWnd
            if not hwnd:
                return {"success": False, "message": f"Could not get window handle for {canonical}."}
            from automation.apps import _get_window_pid
            pid = _get_window_pid(hwnd)
            pids = apps.collect_process_pids(process_name)
            if pid not in pids:
                return {"success": False, "message": f"Active window does not belong to {canonical}."}
            title = active.title.strip()
            logger.info(
                "Intent=CLOSE_APPLICATION App=%s Action=close_active_window PID=%d HWND=%d Title=%s",
                canonical, pid, hwnd, title or "(untitled)",
            )
            active.close()
            deadline = time.monotonic() + 3.0
            while time.monotonic() < deadline:
                if not apps.is_process_running(process_name):
                    logger.info(
                        "Intent=CLOSE_APPLICATION App=%s Action=close_active_window PID=%d Success=True",
                        canonical, pid,
                    )
                    return {"success": True, "message": f"{canonical} window closed.", "details": {"app": canonical, "method": "active_window", "pid": pid, "hwnd": hwnd, "title": title}}
                time.sleep(0.2)
            logger.info(
                "Intent=CLOSE_APPLICATION App=%s Action=close_active_window PID=%d Success=False",
                canonical, pid,
            )
            return {"success": False, "message": f"Active {canonical} window did not close.", "details": {"needs_force_close": True}}
        except Exception as exc:
            logger.warning("Intent=CLOSE_APPLICATION App=%s Action=close_active_window Error=%s", canonical, exc)
            return {"success": False, "message": f"Failed to close active window for {canonical}: {exc}"}

    @staticmethod
    def _prompt_multiple_instances(
        app_name: str,
        count: int,
        voice_input: Callable[[], str | None] | None,
    ) -> str:
        """Ask the user whether to close all instances or only the active one."""
        msg = f"I found {count} {app_name} windows.\nClose all or only the active one?"
        print(msg)

        if voice_input is not None:
            raw = voice_input()
            if raw is None:
                reply = input("(all/active/cancel): ").strip().casefold()
            else:
                reply = raw.strip().casefold()
        else:
            reply = input("(all/active/cancel): ").strip().casefold()

        if reply in ("all", "a", "close all"):
            logger.info("Intent=CLOSE_APPLICATION Action=multi_instance_choice Choice=all")
            return "all"
        if reply in ("active", "current", "foreground", "this one"):
            logger.info("Intent=CLOSE_APPLICATION Action=multi_instance_choice Choice=active")
            return "active"
        logger.info("Intent=CLOSE_APPLICATION Action=multi_instance_choice Choice=cancel")
        return "cancel"

    # ------------------------------------------------------------------
    # Focus app
    # ------------------------------------------------------------------

    def _focus_app(self, target: str) -> dict:
        app_info = self._resolve_app(target)
        if app_info is None:
            return self._app_not_found(target)
        if isinstance(app_info, dict) and app_info.get("needs_clarification"):
            names = app_info["names"]
            return {"success": False, "message": f"Did you mean: {', '.join(names)}?"}

        process_name = app_info.process_name
        if not apps.is_process_running(process_name):
            logger.info("Intent=FOCUS_APPLICATION App=%s Action=none_needed Success=True", app_info.canonical_name)
            return self._not_running_msg(app_info.canonical_name)

        result = apps.focus_process(process_name, display_name=app_info.canonical_name)
        logger.info("Intent=FOCUS_APPLICATION App=%s Matched=%s Success=%s", target, app_info.canonical_name, result["success"])
        return result

    # ------------------------------------------------------------------
    # Restart app
    # ------------------------------------------------------------------

    def _restart_app(self, target: str) -> dict:
        app_info = self._resolve_app(target)
        if app_info is None:
            return self._app_not_found(target)
        if isinstance(app_info, dict) and app_info.get("needs_clarification"):
            names = app_info["names"]
            return {"success": False, "message": f"Did you mean: {', '.join(names)}?"}

        process_name = app_info.process_name
        logger.info("Intent=RESTART_APPLICATION App=%s Matched=%s", target, app_info.canonical_name)

        pids = [p.info["pid"] for p in psutil.process_iter(["name", "pid"]) if p.info.get("name", "").casefold() == process_name.casefold()]

        # Close
        if apps.is_process_running(process_name):
            close_result = apps.close_process(process_name, wait_seconds=2.0, display_name=app_info.canonical_name)
            if not close_result.get("success"):
                apps.force_process_kill(process_name)
            time.sleep(0.5)

        # Launch
        launch_result = apps.launch_executable(app_info.executable, [], process_name)
        if not launch_result["success"]:
            logger.error("Intent=RESTART_APPLICATION App=%s Action=launch Success=False", app_info.canonical_name)
            return {"success": False, "message": f"Failed to restart {app_info.canonical_name}. Could not launch.", "details": {"app": app_info.canonical_name}}

        launched = apps.verify_launch_by_process(process_name)
        if launched:
            new_pids = [str(p.info["pid"]) for p in psutil.process_iter(["name", "pid"]) if p.info.get("name", "").casefold() == process_name.casefold()]
            logger.info("Intent=RESTART_APPLICATION App=%s Action=restarted OldPID=%s NewPID=%s Success=True",
                         app_info.canonical_name, ",".join(str(p) for p in pids[:2]) if pids else "unknown", ",".join(new_pids[:2]) if new_pids else "unknown")
            return self._success_msg(app_info.canonical_name, "restarted")

        logger.warning("Intent=RESTART_APPLICATION App=%s Action=verify_launch Success=False", app_info.canonical_name)
        return {"success": False, "message": f"Failed to restart {app_info.canonical_name}. Could not verify launch.", "details": {"app": app_info.canonical_name}}

    # ------------------------------------------------------------------
    # Minimize / Maximize / Restore
    # ------------------------------------------------------------------

    def _minimize_app(self, target: str) -> dict:
        app_info = self._resolve_app(target)
        if app_info is None:
            return self._app_not_found(target)
        if isinstance(app_info, dict) and app_info.get("needs_clarification"):
            return {"success": False, "message": f"Did you mean: {', '.join(app_info['names'])}?"}

        result = apps.minimize_process(app_info.process_name, display_name=app_info.canonical_name)
        logger.info("Intent=MINIMIZE_APPLICATION App=%s Matched=%s Success=%s", target, app_info.canonical_name, result["success"])
        return result

    def _maximize_app(self, target: str) -> dict:
        app_info = self._resolve_app(target)
        if app_info is None:
            return self._app_not_found(target)
        if isinstance(app_info, dict) and app_info.get("needs_clarification"):
            return {"success": False, "message": f"Did you mean: {', '.join(app_info['names'])}?"}

        result = apps.maximize_process(app_info.process_name, display_name=app_info.canonical_name)
        logger.info("Intent=MAXIMIZE_APPLICATION App=%s Matched=%s Success=%s", target, app_info.canonical_name, result["success"])
        return result

    def _restore_app(self, target: str) -> dict:
        app_info = self._resolve_app(target)
        if app_info is None:
            return self._app_not_found(target)
        if isinstance(app_info, dict) and app_info.get("needs_clarification"):
            return {"success": False, "message": f"Did you mean: {', '.join(app_info['names'])}?"}

        result = apps.restore_process(app_info.process_name, display_name=app_info.canonical_name)
        logger.info("Intent=RESTORE_APPLICATION App=%s Matched=%s Success=%s", target, app_info.canonical_name, result["success"])
        return result

    # ------------------------------------------------------------------
    # Close all applications
    # ------------------------------------------------------------------

    def _close_all_apps(self) -> dict:
        logger.info("Intent=CLOSE_ALL_APPLICATIONS")
        result = apps.close_all_user_apps()
        logger.info("Intent=CLOSE_ALL_APPLICATIONS Closed=%d Success=%s",
                     len(result.get("details", {}).get("closed", [])), result["success"])
        return result


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
        "open_website",
        "search",
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
        if step.action in ("navigate", "open_website"):
            url = step.parameters.get("url") or step.target
            if not isinstance(url, str) or not url.strip():
                raise StepParameterError(
                    f"Step action {step.action!r} requires a non-empty 'url' parameter or target."
                )
            return browser.open_url(url)

        if step.action in ("browser_search", "search"):
            provider = step.parameters.get("provider", "google")
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


class SpecialFolderHandler:
    """Adapter for opening Windows special folders."""

    _SUPPORTED_ACTIONS = {"open_special_folder"}

    def run(self, step: Step, **kwargs: Any) -> Any:
        if step.action == "open_special_folder":
            folder = _require_target(step)
            return apps.open_special_folder(folder)

        raise UnsupportedActionError(
            handler_name="SpecialFolderHandler",
            action=step.action,
            supported=self._SUPPORTED_ACTIONS,
        )


class SettingsHandler:
    """Adapter for opening Windows Settings pages."""

    _SUPPORTED_ACTIONS = {"open_settings"}

    def run(self, step: Step, **kwargs: Any) -> Any:
        if step.action == "open_settings":
            page = step.parameters.get("page", "")
            return apps.open_settings(page)

        raise UnsupportedActionError(
            handler_name="SettingsHandler",
            action=step.action,
            supported=self._SUPPORTED_ACTIONS,
        )


class VolumeHandler:
    """Adapter for volume control actions."""

    _SUPPORTED_ACTIONS = {
        "increase_volume",
        "decrease_volume",
        "set_volume",
        "mute_volume",
        "unmute_volume",
    }

    def run(self, step: Step, **kwargs: Any) -> Any:
        if step.action == "increase_volume":
            amount = step.parameters.get("amount", 10)
            return apps.increase_volume(amount)

        if step.action == "decrease_volume":
            amount = step.parameters.get("amount", 10)
            return apps.decrease_volume(amount)

        if step.action == "set_volume":
            level = step.parameters.get("level", 50)
            return apps.set_volume(level)

        if step.action == "mute_volume":
            return apps.mute_volume()

        if step.action == "unmute_volume":
            return apps.unmute_volume()

        raise UnsupportedActionError(
            handler_name="VolumeHandler",
            action=step.action,
            supported=self._SUPPORTED_ACTIONS,
        )


class ScreenshotHandler:
    """Adapter for screenshot actions."""

    _SUPPORTED_ACTIONS = {"screenshot"}

    def run(self, step: Step, **kwargs: Any) -> Any:
        if step.action == "screenshot":
            return apps.take_screenshot()

        raise UnsupportedActionError(
            handler_name="ScreenshotHandler",
            action=step.action,
            supported=self._SUPPORTED_ACTIONS,
        )


class SystemHandler:
    """Adapter for system commands: lock, shutdown, restart, sleep,
    brightness, WiFi, Bluetooth, airplane mode, system status,
    sign out, system tools, format drive, kill process, and delayed
    shutdown/restart."""

    _SUPPORTED_ACTIONS = {
        "lock",
        "shutdown",
        "restart",
        "sleep",
        "set_brightness",
        "wifi_on",
        "wifi_off",
        "bluetooth_on",
        "bluetooth_off",
        "airplane_mode_on",
        "airplane_mode_off",
        "system_status",
        "sign_out",
        "cancel_shutdown",
        "open_task_manager",
        "open_device_manager",
        "open_control_panel",
        "format_drive",
        "kill_process",
    }

    def run(self, step: Step, **kwargs: Any) -> Any:
        if step.action == "lock":
            return apps.lock_workstation()

        if step.action == "shutdown":
            return self._shutdown(step)

        if step.action == "restart":
            return self._restart(step)

        if step.action == "sleep":
            return apps.sleep_computer()

        if step.action == "set_brightness":
            level = step.parameters.get("level", 50)
            return system_ops.set_brightness(level)

        if step.action == "wifi_on":
            return system_ops.wifi_on()

        if step.action == "wifi_off":
            return system_ops.wifi_off()

        if step.action == "bluetooth_on":
            return system_ops.bluetooth_on()

        if step.action == "bluetooth_off":
            return system_ops.bluetooth_off()

        if step.action == "airplane_mode_on":
            return system_ops.airplane_mode_on()

        if step.action == "airplane_mode_off":
            return system_ops.airplane_mode_off()

        if step.action == "system_status":
            return self._system_status(step)

        if step.action == "sign_out":
            return system_ops.sign_out()

        if step.action == "cancel_shutdown":
            return system_ops.cancel_delayed_shutdown()

        if step.action == "open_task_manager":
            return system_ops.open_system_tool("task manager")

        if step.action == "open_device_manager":
            return system_ops.open_system_tool("device manager")

        if step.action == "open_control_panel":
            return system_ops.open_system_tool("control panel")

        if step.action == "format_drive":
            drive = step.parameters.get("drive", "")
            if not drive:
                return {"success": False, "message": "No drive specified."}
            return system_ops.format_drive(drive)

        if step.action == "kill_process":
            process = step.parameters.get("process", "")
            if not process:
                return {"success": False, "message": "No process specified."}
            return apps.force_process_kill(process)

        raise UnsupportedActionError(
            handler_name="SystemHandler",
            action=step.action,
            supported=self._SUPPORTED_ACTIONS,
        )

    @staticmethod
    def _shutdown(step: Step) -> dict:
        delay = step.parameters.get("delay_seconds")
        if delay:
            return system_ops.delayed_shutdown(seconds=int(delay))
        return apps.shutdown_computer()

    @staticmethod
    def _restart(step: Step) -> dict:
        delay = step.parameters.get("delay_seconds")
        if delay:
            return system_ops.delayed_restart(seconds=int(delay))
        return apps.restart_computer()

    @staticmethod
    def _system_status(step: Step) -> dict:
        query = step.parameters.get("query", "all")
        q = query.strip().casefold()
        if q in ("cpu", "processor"):
            return system_ops.get_cpu_usage()
        if q in ("cpu_top", "cpu top", "top cpu"):
            return system_ops.get_top_cpu_processes()
        if q in ("ram", "memory", "mem"):
            return system_ops.get_ram_usage()
        if q in ("disk", "drive", "storage"):
            return system_ops.get_disk_usage()
        if q in ("network", "net", "internet"):
            return system_ops.get_network_usage()
        if q in ("battery", "battery status", "power"):
            return system_ops.get_battery_status()
        if q in ("brightness",):
            return system_ops.get_brightness()
        # "all" — return a combined report
        parts = [
            system_ops.get_battery_status(),
            system_ops.get_cpu_usage(),
            system_ops.get_ram_usage(),
            system_ops.get_disk_usage(),
        ]
        errors = [p["message"] for p in parts if p.get("success")]
        msg = " | ".join(errors) if errors else "Could not retrieve system status."
        return {"success": True, "message": msg, "details": parts}


class FileManagerHandler:
    """Adapter for file management actions.

    Supports: open_file, find_file, open_file_location,
              copy_file, move_file, rename_file, delete_file.
    """

    _SUPPORTED_ACTIONS = {
        "open_file",
        "find_file",
        "open_file_location",
        "copy_file",
        "move_file",
        "rename_file",
        "delete_file",
    }

    def __init__(self) -> None:
        self._file_memory = FileMemory()

    def run(self, step: Step, voice_input: Callable[[], str | None] | None = None) -> Any:
        if step.action == "open_file":
            return self._open_file(step, voice_input)
        if step.action == "find_file":
            return self._find_file(step, voice_input)
        if step.action == "open_file_location":
            return self._open_file_location(step)
        if step.action == "copy_file":
            return self._copy_file(step)
        if step.action == "move_file":
            return self._move_file(step)
        if step.action == "rename_file":
            return self._rename_file(step)
        if step.action == "delete_file":
            return self._delete_file(step, voice_input)

        raise UnsupportedActionError(
            handler_name="FileManagerHandler",
            action=step.action,
            supported=self._SUPPORTED_ACTIONS,
        )

    # ------------------------------------------------------------------
    # Open file
    # ------------------------------------------------------------------

    def _open_file(
        self,
        step: Step,
        voice_input: Callable[[], str | None] | None,
    ) -> dict:
        file_query = step.parameters.get("file_query", step.target or "")
        if not file_query:
            return {"success": False, "message": "No file specified."}

        # Try the exact path only — do not search or invent a path.
        result = file_ops.open_file(file_query)
        if result.get("success"):
            self._file_memory.record_access(result["details"]["path"])
            return result

        # File not found at the exact path — report and stop.
        return result

    @staticmethod
    def _prompt_file_choice(
        names: list[str],
        voice_input: Callable[[], str | None] | None,
    ) -> int | None:
        """Ask the user which file to open when multiple matches exist."""
        print("I found multiple files:")
        for i, name in enumerate(names, 1):
            print(f"{i}. {name}")

        if voice_input is not None:
            raw = voice_input()
            if raw is None:
                reply = input("Which one? (1-5 or cancel): ").strip().casefold()
            else:
                reply = raw.strip().casefold()
        else:
            reply = input("Which one? (1-5 or cancel): ").strip().casefold()

        if reply in ("cancel", "c", "none"):
            return None
        try:
            idx = int(reply) - 1
            if 0 <= idx < len(names):
                return idx
        except ValueError:
            pass
        # Try name match
        for i, name in enumerate(names):
            if reply in name.casefold():
                return i
        return None

    # ------------------------------------------------------------------
    # Find file
    # ------------------------------------------------------------------

    def _find_file(
        self,
        step: Step,
        voice_input: Callable[[], str | None] | None,
    ) -> dict:
        file_query = step.parameters.get("file_query", step.target or "")
        if not file_query:
            return {"success": False, "message": "No search query specified."}

        # Search only common folders — do not fall back to memory.
        matches = file_ops.find_file(file_query)
        if not matches:
            return {"success": False, "message": f"No files found matching '{file_query}'."}

        if len(matches) == 1:
            return {
                "success": True,
                "message": f"Found {matches[0]['name']}.",
                "details": {"path": matches[0]["path"], "matches": matches},
            }

        names = [m["name"] for m in matches[:5]]
        choice = self._prompt_file_choice(names, voice_input)
        if choice is None or choice == "cancel":
            return {"success": False, "message": "Cancelled."}
        return {
            "success": True,
            "message": f"Found {matches[choice]['name']}.",
            "details": {"path": matches[choice]["path"], "matches": matches},
        }

    # ------------------------------------------------------------------
    # Open file location
    # ------------------------------------------------------------------

    def _open_file_location(self, step: Step) -> dict:
        file_query = step.parameters.get("file_query", "")
        if not file_query:
            return file_ops.open_containing_folder(".")

        import os as _os
        if _os.path.exists(file_query):
            return file_ops.open_containing_folder(file_query)

        # Exact path not found — report and stop instead of searching.
        return {"success": False, "message": f"Could not find '{file_query}'."}

    # ------------------------------------------------------------------
    # Copy / Move / Rename / Delete
    # ------------------------------------------------------------------

    def _copy_file(self, step: Step) -> dict:
        source = step.parameters.get("source", "")
        destination = step.parameters.get("destination", "")
        if not source or not destination:
            return {"success": False, "message": "Both source and destination are required."}
        return file_ops.copy_file(source, destination)

    def _move_file(self, step: Step) -> dict:
        source = step.parameters.get("source", "")
        destination = step.parameters.get("destination", "")
        if not source or not destination:
            return {"success": False, "message": "Both source and destination are required."}
        return file_ops.move_file(source, destination)

    def _rename_file(self, step: Step) -> dict:
        source = step.parameters.get("source", "")
        new_name = step.parameters.get("new_name", "")
        if not source or not new_name:
            return {"success": False, "message": "Both source and new name are required."}
        return file_ops.rename_file(source, new_name)

    def _delete_file(
        self,
        step: Step,
        voice_input: Callable[[], str | None] | None,
    ) -> dict:
        file_query = step.parameters.get("file_query", step.target or "")
        if not file_query:
            return {"success": False, "message": "No file specified."}

        # Try the exact path only — do not search or invent a path.
        import os as _os
        if _os.path.exists(file_query):
            result = file_ops.delete_file(file_query)
            if result.get("needs_confirmation"):
                ok = self._confirm_delete(result["message"], voice_input)
                if not ok:
                    return {"success": False, "message": "Cancelled."}
                return file_ops.delete_file(file_query, confirmed=True)
            return result

        return {"success": False, "message": f"Could not find '{file_query}'."}

    def _delete_with_confirm(
        self,
        path: str,
        display_name: str,
        voice_input: Callable[[], str | None] | None,
    ) -> dict:
        result = file_ops.delete_file(path)
        if result.get("needs_confirmation"):
            ok = self._confirm_delete(result["message"], voice_input)
            if not ok:
                return {"success": False, "message": "Cancelled."}
            return file_ops.delete_file(path, confirmed=True)
        return result

    @staticmethod
    def _confirm_delete(
        message: str,
        voice_input: Callable[[], str | None] | None,
    ) -> bool:
        print(message)
        if voice_input is not None:
            raw = voice_input()
            if raw is None:
                reply = input("Delete? (yes/no): ").strip().casefold()
            else:
                reply = raw.strip().casefold()
        else:
            reply = input("Delete? (yes/no): ").strip().casefold()
        return reply in ("yes", "y", "confirm", "delete")


class SecurityToolsHandler:
    """Adapter for security / pentest tooling actions.

    Supports: create_pentest_report, organize_scan_results,
              summarize_scan_results, create_pentest_project.
    """

    _SUPPORTED_ACTIONS = {
        "create_pentest_report",
        "organize_scan_results",
        "summarize_scan_results",
        "create_pentest_project",
    }

    def run(self, step: Step, **kwargs: Any) -> Any:
        if step.action == "create_pentest_report":
            client = step.parameters.get("client_name", "")
            project = step.parameters.get("project_name", "")
            return security_tools.create_pentest_report(client, project)

        if step.action == "organize_scan_results":
            source_dir = step.parameters.get("source_dir", "")
            project_name = step.parameters.get("project_name", "")
            return security_tools.organize_scan_results(source_dir, project_name)

        if step.action == "summarize_scan_results":
            file_path = step.parameters.get("file_path", "")
            if not file_path:
                return {"success": False, "message": "No scan file specified."}
            return security_tools.summarize_scan_results(file_path)

        if step.action == "create_pentest_project":
            project_name = step.parameters.get("project_name", "Pentest-Project")
            return security_tools.create_project_structure(project_name)

        raise UnsupportedActionError(
            handler_name="SecurityToolsHandler",
            action=step.action,
            supported=self._SUPPORTED_ACTIONS,
        )


class VisionHandler:
    """Adapter for vision / screen understanding actions."""

    _SUPPORTED_ACTIONS = {
        "read_screen",
        "describe_screen",
        "click_element",
        "find_element",
        "read_pdf",
        "ocr_image",
        "read_error",
        "fill_form",
    }

    def run(self, step: Step, **kwargs: Any) -> Any:
        import automation.vision as vision

        if step.action == "read_screen":
            result = vision.read_screen_text()
            if result["success"]:
                from memory.vision_memory import save_screen_text
                save_screen_text(result["text"], result.get("resolution", ""))
            return result

        if step.action == "describe_screen":
            return vision.describe_screen()

        if step.action == "click_element":
            target = step.parameters.get("target", "")
            if not target:
                return {"success": False, "message": "No target specified."}
            return vision.click_text(target)

        if step.action == "find_element":
            target = step.parameters.get("target", "")
            if not target:
                return {"success": False, "message": "No target specified."}
            result = vision.find_text_on_screen(target)
            if result["success"]:
                from memory.vision_memory import save_found_element
                save_found_element(target, result)
            return result

        if step.action == "read_pdf":
            file_path = step.parameters.get("file_path", "")
            if not file_path:
                return {"success": False, "message": "No file specified."}
            return vision.read_pdf(file_path)

        if step.action == "ocr_image":
            file_path = step.parameters.get("file_path", "")
            if not file_path:
                return {"success": False, "message": "No file specified."}
            return vision.ocr_image(file_path)

        if step.action == "read_error":
            result = vision.read_error_dialog()
            if result["success"]:
                from memory.vision_memory import save_dialog
                save_dialog(result["text"], is_error=result.get("has_error_keywords", False))
            return result

        if step.action == "fill_form":
            field = step.parameters.get("field", "")
            value = step.parameters.get("value", "")
            if not field:
                return {"success": False, "message": "No form field specified."}
            return vision.fill_form_field(field, value)

        raise UnsupportedActionError(
            handler_name="VisionHandler",
            action=step.action,
            supported=self._SUPPORTED_ACTIONS,
        )
