"""
world_model/collectors/files.py — File-system state collector.

Collects:
  - Current working folder (from active Explorer window / shell)
  - Recent files (Windows Recent Items)
  - Downloads in progress (.crdownload / .part files in Downloads folder)
"""

from __future__ import annotations

import logging
import os
import re
from pathlib import Path
from typing import Any

import psutil

from world_model.collectors import BaseCollector, logger

_DOWNLOADS_DIR = str(Path.home() / "Downloads")


class FilesCollector(BaseCollector):
    """Collects file system state: current folder, recent files, downloads."""

    def __init__(self, poll_interval: float = 10.0) -> None:
        super().__init__(poll_interval)
        self._recent_path = self._find_recent_folder()
        self._last_recent: list[str] = []

    def collect(self) -> dict[str, Any]:
        try:
            return self._collect()
        except Exception as exc:
            logger.warning("FilesCollector: %s", exc)
            return {}

    def _collect(self) -> dict[str, Any]:
        current_folder = self._get_current_folder()
        recent = self._get_recent_files()
        downloads = self._get_active_downloads()

        return {
            "files": {
                "current_folder": current_folder,
                "recent_files": recent,
                "downloads_in_progress": downloads,
            },
        }

    # ── Current working folder ─────────────────────────────────────

    @staticmethod
    def _get_current_folder() -> str | None:
        """Return the path of the active File Explorer window, or the
        CWD of the terminal that currently has focus."""
        try:
            # Check foreground process — if it's explorer.exe, try to
            # get its current folder from the window title
            active_pid = _get_foreground_pid()
            if active_pid:
                proc = psutil.Process(active_pid)
                if proc.name().lower() == "explorer.exe":
                    folder = _get_explorer_path(active_pid)
                    if folder:
                        return folder
                # Terminal emulators often have the CWD as part of the title
                title = _get_window_title(active_pid)
                if title:
                    for marker in (r"\\", ":", "~"):
                        if marker in title:
                            parts = re.split(r"\s+[—\-|]\s+", title)
                            for p in parts:
                                p = p.strip()
                                if os.path.isdir(p):
                                    return p

            # Fallback: check common terminals
            for proc in psutil.process_iter(["pid", "name", "cwd"]):
                try:
                    name = (proc.info["name"] or "").lower()
                    if name in ("cmd.exe", "powershell.exe", "pwsh.exe",
                                "windowsTerminal.exe", "wt.exe"):
                        cwd = proc.info.get("cwd")
                        if cwd:
                            return cwd
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    continue
        except Exception:
            pass
        return None

    # ── Recent files ───────────────────────────────────────────────

    @staticmethod
    def _find_recent_folder() -> str | None:
        """Locate the Windows Recent Items folder."""
        try:
            import ctypes
            from ctypes import wintypes
            # CSIDL_RECENT = 0x08
            buf = ctypes.create_unicode_buffer(260)
            ctypes.windll.shell32.SHGetFolderPathW(None, 0x08, None, 0, buf)
            path = buf.value
            return path if os.path.isdir(path) else None
        except Exception:
            return None

    def _get_recent_files(self) -> list[str]:
        """Return a list of recent file paths (max 20)."""
        recent_dir = self._recent_path
        if not recent_dir or not os.path.isdir(recent_dir):
            return self._last_recent
        try:
            entries = sorted(
                recent_dir,
                key=lambda p: os.path.getmtime(p), reverse=True,
            )
            result = []
            for lnk in entries[:20]:
                target = _resolve_lnk(lnk)
                if target and os.path.isfile(target):
                    result.append(target)
            self._last_recent = result
            return result
        except Exception:
            return self._last_recent

    # ── Active downloads ───────────────────────────────────────────

    @staticmethod
    def _get_active_downloads() -> list[str]:
        """Return paths of in-progress downloads (matching *.crdownload, *.part)."""
        dldir = _DOWNLOADS_DIR
        if not os.path.isdir(dldir):
            return []
        try:
            entries = []
            for f in os.listdir(dldir):
                if f.endswith((".crdownload", ".part", ".download")):
                    full = os.path.join(dldir, f)
                    entries.append(full)
            return entries
        except Exception:
            return []


# ── Module-level helpers (shared with other collectors if needed) ────


def _get_foreground_pid() -> int | None:
    try:
        import ctypes
        from ctypes import wintypes
        user32 = ctypes.windll.user32
        hwnd = user32.GetForegroundWindow()
        pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        return pid.value
    except Exception:
        return None


def _get_window_title(pid: int) -> str | None:
    try:
        import ctypes
        from ctypes import wintypes
        user32 = ctypes.windll.user32
        titles = []

        def _enum_cb(hwnd, _lp):
            b = ctypes.create_unicode_buffer(
                user32.GetWindowTextLengthW(hwnd) + 1,
            )
            user32.GetWindowTextW(hwnd, b, len(b))
            t = b.value
            if not t:
                return True
            wp = wintypes.DWORD()
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(wp))
            if wp.value == pid and user32.IsWindowVisible(hwnd):
                titles.append(t)
            return True

        cb = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_int, ctypes.c_int)(_enum_cb)
        user32.EnumWindows(cb, 0)
        return max(titles, key=len) if titles else None
    except Exception:
        return None


def _get_explorer_path(pid: int) -> str | None:
    """Try to extract the current Explorer folder path for a given PID."""
    try:
        import ctypes
        ole32 = ctypes.windll.ole32
        ole32.CoInitialize(None)

        from ctypes import wintypes
        import pythoncom
        from win32com.client import Dispatch

        shell = Dispatch("Shell.Application")
        for w in shell.Windows():
            try:
                if w.Accelerators:
                    pass
                # Match by HWND → PID
                hwnd = w.HWND
                wp = wintypes.DWORD()
                ctypes.windll.user32.GetWindowThreadProcessId(hwnd, ctypes.byref(wp))
                if wp.value == pid:
                    path = w.Document.Folder.Self.Path
                    if path:
                        ole32.CoUninitialize()
                        return path
            except Exception:
                continue
        ole32.CoUninitialize()
    except Exception:
        pass
    return None


def _resolve_lnk(path: str) -> str | None:
    """Resolve a .lnk shortcut to its target path."""
    try:
        import ctypes
        ole32 = ctypes.windll.ole32
        ole32.CoInitialize(None)

        import pythoncom
        from win32com.client import Dispatch

        shell = Dispatch("WScript.Shell")
        shortcut = shell.CreateShortCut(path)
        target = shortcut.TargetPath
        ole32.CoUninitialize()
        return target if os.path.isfile(target) else None
    except Exception:
        return None
