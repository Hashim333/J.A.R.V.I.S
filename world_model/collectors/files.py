"""
world_model/collectors/files.py — File-system state collector.

Collects:
  - Current working folder (from the active Explorer window / terminal)
  - Recent files (Windows Recent Items)
  - Downloads in progress (``.crdownload`` / ``.part`` in Downloads)
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

import psutil

from world_model.collectors import BaseCollector, logger
from world_model.collectors import win32_shell, win32_windows

_DOWNLOADS_DIR = str(Path.home() / "Downloads")
_MAX_RECENT_FILES = 20
_DOWNLOAD_SUFFIXES = (".crdownload", ".part", ".download")

# Terminal hosts whose title (or process CWD) carries a working folder.
# All lowercase: the previous tuple mixed cases, so ``windowsTerminal.exe``
# could never match a name that had already been case-folded.
_TERMINAL_NAMES = frozenset({
    "cmd.exe", "powershell.exe", "pwsh.exe",
    "windowsterminal.exe", "wt.exe", "conhost.exe",
})


class FilesCollector(BaseCollector):
    """Collects file system state: current folder, recent files, downloads."""

    def __init__(self, poll_interval: float = 10.0) -> None:
        super().__init__(poll_interval)
        self._recent_path = win32_shell.recent_items_folder()
        self._last_recent: list[str] = []

    def collect(self) -> dict[str, Any]:
        try:
            return self._collect()
        except Exception as exc:
            logger.warning("FilesCollector: %s", exc)
            return {}

    def _collect(self) -> dict[str, Any]:
        return {
            "files": {
                "current_folder": self._get_current_folder(),
                "recent_files": self._get_recent_files(),
                "downloads_in_progress": self._get_active_downloads(),
            },
        }

    # ── Current working folder ─────────────────────────────────────

    @staticmethod
    def _get_current_folder() -> str | None:
        """Active Explorer window's folder, or the focused terminal's CWD."""
        try:
            active_pid = win32_windows.foreground_pid()
            if active_pid:
                if _process_name(active_pid) == "explorer.exe":
                    folder = win32_shell.explorer_folder_for_pid(active_pid)
                    if folder:
                        return folder
                # Terminals embed the current folder in the window title.
                folder = _folder_from_title(
                    win32_windows.window_title_for_pid(active_pid),
                )
                if folder:
                    return folder
            return _terminal_cwd()
        except Exception as exc:
            logger.debug("FilesCollector: current folder probe failed: %s", exc)
            return None

    # ── Recent files ───────────────────────────────────────────────

    def _get_recent_files(self) -> list[str]:
        """Most recently used file paths (newest first, max 20)."""
        recent_dir = self._recent_path
        if not recent_dir or not os.path.isdir(recent_dir):
            return self._last_recent
        try:
            # The previous version ran ``sorted(recent_dir, ...)`` — iterating
            # the path *string* and calling getmtime() on each character — so
            # this always raised and recent files were never reported.
            shortcuts = [
                os.path.join(recent_dir, name)
                for name in os.listdir(recent_dir)
                if name.lower().endswith(".lnk")
            ]
        except OSError as exc:
            logger.debug("FilesCollector: recent items unreadable: %s", exc)
            return self._last_recent

        shortcuts.sort(key=_modified_time, reverse=True)
        result: list[str] = []
        for shortcut in shortcuts[:_MAX_RECENT_FILES]:
            target = win32_shell.resolve_shortcut(shortcut)
            if target:
                result.append(target)
        self._last_recent = result
        return result

    # ── Active downloads ───────────────────────────────────────────

    @staticmethod
    def _get_active_downloads() -> list[str]:
        """Paths of in-progress downloads in the Downloads folder."""
        if not os.path.isdir(_DOWNLOADS_DIR):
            return []
        try:
            return [
                os.path.join(_DOWNLOADS_DIR, name)
                for name in os.listdir(_DOWNLOADS_DIR)
                if name.lower().endswith(_DOWNLOAD_SUFFIXES)
            ]
        except OSError as exc:
            logger.debug("FilesCollector: downloads unreadable: %s", exc)
            return []


# ── Module-level helpers ───────────────────────────────────────────


def _process_name(pid: int) -> str:
    try:
        return psutil.Process(pid).name().lower()
    except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
        return ""


def _modified_time(path: str) -> float:
    """Modification time, or 0.0 when the entry vanished mid-listing."""
    try:
        return os.path.getmtime(path)
    except OSError:
        return 0.0


def _folder_from_title(title: str | None) -> str | None:
    """Return the folder embedded in a window title, if it is a real one."""
    if not title:
        return None
    if not any(marker in title for marker in ("\\", ":", "~")):
        return None
    for part in re.split(r"\s+[—\-|]\s+", title):
        candidate = part.strip()
        if candidate and os.path.isdir(candidate):
            return candidate
    return None


def _terminal_cwd() -> str | None:
    """Working directory of a running terminal, if one can be read."""
    for proc in psutil.process_iter(["name", "cwd"]):
        try:
            name = (proc.info["name"] or "").lower()
            if name in _TERMINAL_NAMES:
                cwd = proc.info.get("cwd")
                if cwd:
                    return cwd
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    return None
