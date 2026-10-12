"""
world_model/collectors/win32_windows.py — Safe Win32 window enumeration.

Both :mod:`world_model.collectors.media` and
:mod:`world_model.collectors.files` need the same Win32 primitives: find the
foreground window's process, map a process to its visible window title, and
walk every visible top-level window.

They previously hand-rolled these calls with ``ctypes.windll`` and no
``argtypes``.  On 64-bit Windows an untyped ``HWND`` argument is marshalled as
a 32-bit C ``int``, so the window handle was truncated before it reached
user32 and the call operated on a wild pointer.  Every entry point here
declares its signature once, and the enumeration callback is typed with
``wintypes`` so handles survive the round trip intact.
"""

from __future__ import annotations

import logging
from ctypes import WINFUNCTYPE, byref, create_unicode_buffer
from ctypes import wintypes

logger = logging.getLogger(__name__)

# A window title longer than this is truncated; it only feeds heuristics.
_MAX_TITLE_CHARS = 512

# user32.EnumWindows callback signature: BOOL CALLBACK(HWND, LPARAM).
_WNDENUMPROC = WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

_user32: object | None = None


def _get_user32():
    """Return a user32 handle with explicit signatures, or ``None``."""
    global _user32
    if _user32 is not None:
        return _user32
    try:
        from ctypes import WinDLL

        user32 = WinDLL("user32", use_last_error=True)

        user32.GetForegroundWindow.argtypes = []
        user32.GetForegroundWindow.restype = wintypes.HWND

        user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, wintypes.LPDWORD]
        user32.GetWindowThreadProcessId.restype = wintypes.DWORD

        user32.GetWindowTextLengthW.argtypes = [wintypes.HWND]
        user32.GetWindowTextLengthW.restype = wintypes.INT

        user32.GetWindowTextW.argtypes = [
            wintypes.HWND, wintypes.LPWSTR, wintypes.INT,
        ]
        user32.GetWindowTextW.restype = wintypes.INT

        user32.IsWindowVisible.argtypes = [wintypes.HWND]
        user32.IsWindowVisible.restype = wintypes.BOOL

        user32.EnumWindows.argtypes = [_WNDENUMPROC, wintypes.LPARAM]
        user32.EnumWindows.restype = wintypes.BOOL
    except Exception as exc:
        logger.warning("win32 window API unavailable: %s", exc)
        return None
    _user32 = user32
    return user32


def foreground_pid() -> int | None:
    """Process id owning the foreground window, or ``None``."""
    user32 = _get_user32()
    if user32 is None:
        return None
    try:
        hwnd = user32.GetForegroundWindow()
        if not hwnd:
            return None
        pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, byref(pid))
        return int(pid.value) or None
    except Exception as exc:
        logger.debug("foreground_pid failed: %s", exc)
        return None


def window_pid(hwnd: int) -> int:
    """Process id owning *hwnd* (0 when it cannot be resolved)."""
    user32 = _get_user32()
    if user32 is None or not hwnd:
        return 0
    try:
        pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, byref(pid))
        return int(pid.value)
    except Exception as exc:
        logger.debug("window_pid failed: %s", exc)
        return 0


def window_title(hwnd: int) -> str:
    """Window text for *hwnd* (empty string when it has none)."""
    user32 = _get_user32()
    if user32 is None or not hwnd:
        return ""
    try:
        length = int(user32.GetWindowTextLengthW(hwnd))
        if length <= 0:
            return ""
        buffer = create_unicode_buffer(min(length, _MAX_TITLE_CHARS) + 1)
        user32.GetWindowTextW(hwnd, buffer, len(buffer))
        return buffer.value
    except Exception as exc:
        logger.debug("window_title failed: %s", exc)
        return ""


def iter_visible_windows() -> list[tuple[int, str, int]]:
    """Return ``(hwnd, title, pid)`` for every visible titled window.

    A single ``EnumWindows`` sweep replaces the per-caller enumeration that
    used to be duplicated in the media and files collectors.
    """
    user32 = _get_user32()
    if user32 is None:
        return []

    found: list[tuple[int, str, int]] = []

    def _callback(hwnd, _lparam):
        try:
            if not user32.IsWindowVisible(hwnd):
                return True
            title = window_title(hwnd)
            if not title:
                return True
            pid = wintypes.DWORD()
            user32.GetWindowThreadProcessId(hwnd, byref(pid))
            found.append((int(hwnd), title, int(pid.value)))
        except Exception as exc:
            logger.debug("window enumeration callback failed: %s", exc)
        return True

    try:
        user32.EnumWindows(_WNDENUMPROC(_callback), 0)
    except Exception as exc:
        logger.debug("EnumWindows failed: %s", exc)
    return found


def window_title_for_pid(pid: int) -> str | None:
    """Longest visible window title owned by *pid*, or ``None``."""
    if not pid:
        return None
    titles = [title for _hwnd, title, owner in iter_visible_windows() if owner == pid]
    return max(titles, key=len) if titles else None
