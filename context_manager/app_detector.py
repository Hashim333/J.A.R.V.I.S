from __future__ import annotations

import logging
from dataclasses import dataclass

import psutil

logger = logging.getLogger(__name__)


@dataclass
class WindowState:
    hwnd: int
    title: str
    pid: int
    is_minimized: bool
    is_maximized: bool
    is_focused: bool
    is_visible: bool


@dataclass
class AppStatus:
    process_name: str
    display_name: str
    running: bool
    windows: list[WindowState]


class AppDetector:
    def detect(self, process_name: str, display_name: str = "") -> AppStatus:
        pn = process_name if process_name.casefold().endswith(".exe") else f"{process_name}.exe"
        pids = self._collect_pids(pn)
        windows = self._detect_windows(pids, display_name or process_name)
        return AppStatus(
            process_name=pn,
            display_name=display_name or pn,
            running=len(pids) > 0,
            windows=windows,
        )

    def _collect_pids(self, process_name: str) -> set[int]:
        pids: set[int] = set()
        try:
            for proc in psutil.process_iter(["name", "pid"]):
                try:
                    if proc.info.get("name", "").casefold() == process_name.casefold():
                        pids.add(proc.info["pid"])
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    continue
        except Exception:
            pass
        return pids

    def _detect_windows(self, pids: set[int], display_name: str) -> list[WindowState]:
        if not pids:
            return []

        import pygetwindow as gw
        foreground = gw.getActiveWindow()
        fg_hwnd = foreground._hWnd if foreground else None

        windows: list[WindowState] = []

        for window in gw.getAllWindows():
            try:
                hwnd = window._hWnd
                if not hwnd:
                    continue
                pid = self._get_window_pid(hwnd)
                if pid not in pids:
                    continue
                title = window.title.strip()
                windows.append(WindowState(
                    hwnd=hwnd,
                    title=title,
                    pid=pid,
                    is_minimized=window.isMinimized,
                    is_maximized=window.isMaximized,
                    is_focused=hwnd == fg_hwnd,
                    is_visible=bool(title) and not window.isMinimized,
                ))
            except Exception:
                continue

        if not windows and display_name:
            windows = self._title_fallback(display_name)
            windows = [w for w in windows if w.pid in pids]

        return windows

    def _title_fallback(self, display_name: str) -> list[WindowState]:
        import pygetwindow as gw
        foreground = gw.getActiveWindow()
        fg_hwnd = foreground._hWnd if foreground else None
        pattern = display_name.casefold().strip()
        results: list[WindowState] = []
        for window in gw.getAllWindows():
            try:
                title = window.title.strip()
                if not title:
                    continue
                if pattern in title.casefold():
                    hwnd = window._hWnd
                    if hwnd:
                        pid = self._get_window_pid(hwnd)
                        results.append(WindowState(
                            hwnd=hwnd, title=title, pid=pid,
                            is_minimized=window.isMinimized,
                            is_maximized=window.isMaximized,
                            is_focused=hwnd == fg_hwnd,
                            is_visible=bool(title) and not window.isMinimized,
                        ))
            except Exception:
                continue
        return results

    @staticmethod
    def _get_window_pid(hwnd: int) -> int:
        import ctypes
        user32 = ctypes.windll.user32
        pid = ctypes.c_ulong()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        return pid.value
