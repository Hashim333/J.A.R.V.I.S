"""
system_awareness/collectors/windows.py — open-window collector.

Collects every top-level visible window (title, pid, active/visible flags)
via the Win32 EnumWindows API.  The focused window is derived from the
foreground HWND.
"""

from __future__ import annotations

import logging
import time
from typing import Any

from world_model.collectors import BaseCollector, logger


class WindowsCollector(BaseCollector):
    """Collects open top-level windows and the focused window."""

    def __init__(self, poll_interval: float = 2.0) -> None:
        super().__init__(poll_interval)

    def collect(self) -> dict[str, Any]:
        try:
            return self._collect()
        except Exception as exc:
            logger.warning("WindowsCollector: %s", exc)
            return {}

    def _collect(self) -> dict[str, Any]:
        import ctypes
        from ctypes import wintypes

        user32 = ctypes.windll.user32
        foreground = user32.GetForegroundWindow()
        windows: list[dict[str, Any]] = []

        @ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_int, ctypes.c_int)
        def _enum_callback(hwnd, _lparam):
            if not user32.IsWindowVisible(hwnd):
                return True
            length = user32.GetWindowTextLengthW(hwnd) + 1
            if length <= 1:
                return True
            buf = ctypes.create_unicode_buffer(length)
            user32.GetWindowTextW(hwnd, buf, length)
            title = buf.value
            if not title:
                return True
            pid = wintypes.DWORD()
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            windows.append({
                "hwnd": int(hwnd),
                "pid": int(pid.value),
                "title": title,
                "is_active": int(hwnd) == int(foreground),
                "is_visible": True,
            })
            return True

        user32.EnumWindows(_enum_callback, 0)

        focused = next(
            (w["title"] for w in windows if w["is_active"]),
            None,
        )
        return {"windows": windows, "focused_window": focused}
