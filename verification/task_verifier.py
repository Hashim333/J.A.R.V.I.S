from __future__ import annotations

import logging
import time
from typing import Any

import psutil

from context_manager.app_detector import AppDetector
from context_manager.browser_detector import BrowserDetector
from context_manager.clarification_engine import ClarificationType
from models.response import Response
from verification.dialog_detector import (
    DialogInfo,
    DialogType,
    detect_blocking_dialog,
)
from verification.profile_handler import ChromeProfileHandler

logger = logging.getLogger(__name__)


class TaskVerifier:
    def __init__(
        self,
        app_detector: AppDetector | None = None,
        browser_detector: BrowserDetector | None = None,
    ) -> None:
        self._app_detector = app_detector or AppDetector()
        self._browser_detector = browser_detector or BrowserDetector()
        self._profile_handler = ChromeProfileHandler(app_detector=self._app_detector)
        self._pending_verification: dict[str, Any] | None = None

    @property
    def has_pending(self) -> bool:
        return self._pending_verification is not None

    def get_pending_context(self) -> dict[str, Any]:
        return self._pending_verification or {}

    def verify(
        self,
        response: Response,
        intent: str,
        entities: dict[str, Any],
    ) -> Response:
        self._pending_verification = None

        if not response.success:
            return response

        if intent == "open_app":
            return self._verify_open_app(response, entities)

        return response

    def resolve(self, answer: str) -> Response | None:
        if not self._pending_verification:
            return None

        pending = self._pending_verification
        check_type = pending.get("check_type", "")

        if check_type == "chrome_profile":
            return self._profile_handler.resolve_profile(answer, pending)
        elif check_type == "dialog":
            dialog = pending.get("dialog_info")
            action = answer.strip().casefold()
            if action in ("yes", "ok", "dismiss", "close", "confirm"):
                return Response(
                    success=True,
                    message=f"{dialog.app_name} is open. You may need to complete the {dialog.dialog_type.name.lower().replace('_', ' ')} manually.",
                    data={"action": "acknowledged"},
                )
            return Response(
                success=True,
                message=f"Continuing with {dialog.app_name}.",
                data={"action": "continue"},
            )

        self._pending_verification = None
        return None

    def clear_pending(self) -> None:
        self._pending_verification = None

    # ------------------------------------------------------------------
    # App verification
    # ------------------------------------------------------------------

    def _verify_open_app(self, response: Response, entities: dict[str, Any]) -> Response:
        app_name = entities.get("app_name", "")
        process_name = entities.get("process_name", f"{app_name}.exe")
        display_name = entities.get("original_app", app_name)

        wait_for_window(app_name, process_name, timeout=3.0)

        dlg = detect_blocking_dialog(app_name, process_name)
        if dlg is None:
            return response

        if dlg.dialog_type == DialogType.PROFILE_PICKER and _is_chrome(process_name):
            return self._profile_handler.handle_chrome_picker(display_name, entities)

        self._pending_verification = {
            "check_type": "dialog",
            "dialog_info": dlg,
            "response": response,
            "entities": entities,
        }
        dlg_type_str = dlg.dialog_type.name.lower().replace("_", " ")
        question = f"{display_name} opened, but a {dlg_type_str} is waiting for your input. Please complete it and let me know when you're done."
        return Response(
            success=False,
            message=question,
            needs_clarification=True,
            clarification_question=question,
            data={"app_name": app_name, "dialog_type": dlg.dialog_type.name},
        )


def wait_for_window(app_name: str, process_name: str, timeout: float = 4.0) -> bool:
    """Wait for a visible top-level window or process matching the app.
    
    Polls every 250ms for up to timeout seconds. Matches case-insensitively
    by process name OR window title. Handles Windows 11 packaged apps where
    the stub process exits and the real process has a different name.
    """
    import ctypes
    from ctypes import wintypes
    
    deadline = time.monotonic() + timeout
    app_lower = app_name.lower()
    proc_lower = process_name.lower().replace(".exe", "")
    
    # EnumWindows callback
    enum_windows = ctypes.windll.user32.EnumWindows
    enum_windows_proc = ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)
    get_window_text = ctypes.windll.user32.GetWindowTextW
    get_window_text_length = ctypes.windll.user32.GetWindowTextLengthW
    is_window_visible = ctypes.windll.user32.IsWindowVisible
    get_window_thread_process_id = ctypes.windll.user32.GetWindowThreadProcessId
    
    def check_windows() -> bool:
        """Check for matching visible top-level windows via EnumWindows."""
        found = False
        
        @enum_windows_proc
        def callback(hwnd: wintypes.HWND, lparam: wintypes.LPARAM) -> bool:
            nonlocal found
            if not is_window_visible(hwnd):
                return True
            length = get_window_text_length(hwnd)
            if length == 0:
                return True
            buffer = ctypes.create_unicode_buffer(length + 1)
            get_window_text(hwnd, buffer, length + 1)
            title = buffer.value.lower()
            if app_lower in title or proc_lower in title:
                found = True
                return False  # Stop enumeration
            return True
        
        enum_windows(callback, 0)
        return found
    
    while time.monotonic() < deadline:
        # Check process existence first (faster)
        try:
            for proc in psutil.process_iter(["name", "pid"]):
                try:
                    pname = proc.info.get("name", "").lower()
                    if proc_lower in pname or app_lower in pname:
                        return True
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    continue
        except Exception:
            pass
        
        # Check visible windows via EnumWindows
        if check_windows():
            return True
        
        time.sleep(0.25)
    
    # Final check
    try:
        for proc in psutil.process_iter(["name", "pid"]):
            try:
                pname = proc.info.get("name", "").lower()
                if proc_lower in pname or app_lower in pname:
                    return True
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
    except Exception:
        pass
    
    return check_windows()


def _is_chrome(process_name: str) -> bool:
    pn = process_name.casefold()
    return "chrome" in pn or "msedge" in pn or "brave" in pn or "opera" in pn or "vivaldi" in pn
