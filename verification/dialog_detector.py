from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from enum import Enum, auto
from typing import Any

logger = logging.getLogger(__name__)


class DialogType(Enum):
    PROFILE_PICKER = auto()
    LOGIN_SCREEN = auto()
    PERMISSION_DIALOG = auto()
    UPDATE_DIALOG = auto()
    CONFIRMATION_DIALOG = auto()
    ACCOUNT_CHOOSER = auto()
    UNKNOWN = auto()


@dataclass
class DialogInfo:
    dialog_type: DialogType
    app_name: str
    window_title: str
    details: str = ""
    detected_via: str = ""


_DIALOG_KEYWORDS: dict[DialogType, list[str]] = {
    DialogType.PROFILE_PICKER: [
        "choose a profile", "select profile", "profile picker",
        "which profile", "switch profile", "profile selection",
    ],
    DialogType.LOGIN_SCREEN: [
        "sign in", "log in", "login", "sign in to continue",
        "enter your password", "enter password", "credentials",
        "sign-in", "log-in",
    ],
    DialogType.PERMISSION_DIALOG: [
        "permission", "allow", "deny", "access requested",
        "would you like to allow", "this app needs permission",
    ],
    DialogType.UPDATE_DIALOG: [
        "update available", "update now", "new version available",
        "install update", "restart to update", "update ready",
        "update required",
    ],
    DialogType.CONFIRMATION_DIALOG: [
        "are you sure", "confirm", "do you want to",
        "this will", "are you sure you want",
    ],
    DialogType.ACCOUNT_CHOOSER: [
        "choose an account", "select account", "pick an account",
        "sign in with", "continue with",
    ],
}


def detect_blocking_dialog(app_name: str, process_name: str) -> DialogInfo | None:
    for method_name, method in [
        ("window_title", _detect_via_window_title),
        ("ocr", _detect_via_ocr),
    ]:
        try:
            result = method(app_name, process_name)
            if result is not None:
                logger.info("DIALOG detected via %s: %s", method_name, result)
                return result
        except Exception as exc:
            logger.debug("DIALOG detection %s failed: %s", method_name, exc)
    return None


def _detect_via_window_title(app_name: str, process_name: str) -> DialogInfo | None:
    import pygetwindow as gw
    try:
        for window in gw.getAllWindows():
            title = window.title.strip().lower()
            if not title or not window.visible:
                continue
            pid = _get_window_pid(window._hWnd)
            if not _pid_matches_process(pid, process_name):
                continue
            for dlg_type, keywords in _DIALOG_KEYWORDS.items():
                for kw in keywords:
                    if kw in title:
                        return DialogInfo(
                            dialog_type=dlg_type,
                            app_name=app_name,
                            window_title=window.title.strip(),
                            details=f"Window title matched '{kw}'",
                            detected_via="window_title",
                        )
    except Exception:
        pass
    return None


def _detect_via_ocr(app_name: str, process_name: str) -> DialogInfo | None:
    from automation.ui_detector import get_screen_text, find_text_on_screen
    try:
        screen_text = get_screen_text().lower()
        for dlg_type, keywords in _DIALOG_KEYWORDS.items():
            for kw in keywords:
                if kw in screen_text:
                    return DialogInfo(
                        dialog_type=dlg_type,
                        app_name=app_name,
                        window_title="(detected via OCR)",
                        details=f"OCR matched '{kw}'",
                        detected_via="ocr",
                    )
    except Exception:
        pass
    return None


def _get_window_pid(hwnd: int) -> int:
    import ctypes
    user32 = ctypes.windll.user32
    pid = ctypes.c_ulong()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    return pid.value


def _pid_matches_process(pid: int, process_name: str) -> bool:
    import psutil
    try:
        proc = psutil.Process(pid)
        return proc.name().casefold() == process_name.casefold()
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        return False
