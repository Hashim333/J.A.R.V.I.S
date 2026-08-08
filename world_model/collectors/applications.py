"""
world_model/collectors/applications.py — Running applications collector.

Collects:
  - All GUI applications with visible windows
  - Active (foreground) window
  - Window titles
  - Process IDs and paths
"""

from __future__ import annotations

import logging
from typing import Any

import psutil

from world_model.collectors import BaseCollector, logger

_WINDOW_TITLE_CACHE: dict[int, str] = {}


class ApplicationsCollector(BaseCollector):
    """Collects running GUI applications and window information."""

    def __init__(self, poll_interval: float = 2.0) -> None:
        super().__init__(poll_interval)

    def collect(self) -> dict[str, Any]:
        try:
            return self._collect()
        except Exception as exc:
            logger.warning("ApplicationsCollector: %s", exc)
            return {}

    def _collect(self) -> dict[str, Any]:
        active_pid = self._get_active_window_pid()
        apps = []

        for proc in psutil.process_iter(["pid", "name", "exe"]):
            try:
                pinfo = proc.info
                if pinfo["name"] is None:
                    continue
                # Skip background-only processes (no window)
                title = self._get_window_title(pinfo["pid"])
                if not title and pinfo["pid"] != active_pid:
                    continue  # skip processes without a visible window
                apps.append({
                    "pid": pinfo["pid"],
                    "name": pinfo["name"],
                    "window_title": title or "",
                    "is_active": pinfo["pid"] == active_pid,
                    "process_path": pinfo["exe"] or "",
                })
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue

        apps.sort(key=lambda a: (-a["is_active"], a["name"].lower()))
        return {"applications": apps}

    # ── Windows helpers ───────────────────────────────────────────

    @staticmethod
    def _get_active_window_pid() -> int:
        """Return the PID of the foreground (active) window on Windows."""
        try:
            import ctypes
            from ctypes import wintypes
            user32 = ctypes.windll.user32
            hwnd = user32.GetForegroundWindow()
            pid = wintypes.DWORD()
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            return pid.value
        except Exception:
            return 0

    @staticmethod
    def _get_window_title(pid: int) -> str | None:
        """Return the window title for a given PID, or None."""
        try:
            import ctypes
            user32 = ctypes.windll.user32
            titles = []

            def _enum_callback(hwnd, _lparam):
                buf_len = user32.GetWindowTextLengthW(hwnd) + 1
                if buf_len <= 1:
                    return True
                buf = ctypes.create_unicode_buffer(buf_len)
                user32.GetWindowTextW(hwnd, buf, buf_len)
                title = buf.value
                if not title:
                    return True
                # Check if this window belongs to the target PID
                from ctypes import wintypes
                win_pid = wintypes.DWORD()
                user32.GetWindowThreadProcessId(hwnd, ctypes.byref(win_pid))
                if win_pid.value == pid and user32.IsWindowVisible(hwnd):
                    titles.append(title)
                return True

            callback = ctypes.WINFUNCTYPE(
                ctypes.c_bool, ctypes.c_int, ctypes.c_int,
            )(_enum_callback)
            user32.EnumWindows(callback, 0)

            if titles:
                return max(titles, key=len)  # most descriptive title
            return None
        except Exception:
            return None
