"""
automation/windows.py

Window context helpers for the automation layer.
"""

from __future__ import annotations

from dataclasses import dataclass

import pygetwindow as gw


class WindowOperationError(Exception):
    """Raised when a window operation cannot be completed."""


@dataclass(frozen=True)
class WindowInfo:
    title: str
    is_active: bool
    is_minimized: bool
    is_maximized: bool


_WINDOW_TITLE_ALIASES: dict[str, tuple[str, ...]] = {
    "chrome": ("chrome", "google chrome"),
    "vscode": ("vscode", "vs code", "visual studio code"),
    "notepad": ("notepad",),
}


def get_active_window() -> str | None:
    """Return the active window title, or None if it cannot be determined."""
    try:
        window = gw.getActiveWindow()
    except Exception as exc:
        raise WindowOperationError(f"Could not get active window: {exc}") from exc

    if window is None:
        return None
    return window.title


def list_windows() -> list[str]:
    """Return visible non-empty window titles."""
    try:
        titles = gw.getAllTitles()
    except Exception as exc:
        raise WindowOperationError(f"Could not list windows: {exc}") from exc

    seen: set[str] = set()
    visible_titles: list[str] = []
    for title in titles:
        clean_title = title.strip()
        if clean_title and clean_title not in seen:
            visible_titles.append(clean_title)
            seen.add(clean_title)
    return visible_titles


def focus_window(title: str) -> bool:
    """Focus the first window whose title contains the requested text."""
    window = _find_window(title)
    if window is None:
        return False

    try:
        if window.isMinimized:
            window.restore()
        window.activate()
        return True
    except Exception as exc:
        raise WindowOperationError(f"Could not focus window {title!r}: {exc}") from exc


def minimize_window(title: str) -> bool:
    """Minimize the first window whose title contains the requested text."""
    window = _find_window(title)
    if window is None:
        return False

    try:
        window.minimize()
        return True
    except Exception as exc:
        raise WindowOperationError(f"Could not minimize window {title!r}: {exc}") from exc


def maximize_window(title: str) -> bool:
    """Maximize the first window whose title contains the requested text."""
    window = _find_window(title)
    if window is None:
        return False

    try:
        window.maximize()
        return True
    except Exception as exc:
        raise WindowOperationError(f"Could not maximize window {title!r}: {exc}") from exc


def restore_window(title: str) -> bool:
    """Restore the first window whose title contains the requested text."""
    window = _find_window(title)
    if window is None:
        return False

    try:
        window.restore()
        return True
    except Exception as exc:
        raise WindowOperationError(f"Could not restore window {title!r}: {exc}") from exc


def _find_window(title: str):
    if not isinstance(title, str) or not title.strip():
        raise WindowOperationError("Window title must be a non-empty string.")

    needles = _window_title_needles(title)
    try:
        windows = gw.getAllWindows()
    except Exception as exc:
        raise WindowOperationError(f"Could not enumerate windows: {exc}") from exc

    for window in windows:
        window_title = window.title.strip()
        haystack = window_title.casefold()
        compact_haystack = _compact_window_text(window_title)
        if window_title and any(
            needle in haystack or _compact_window_text(needle) in compact_haystack
            for needle in needles
        ):
            return window
    return None


def _window_title_needles(title: str) -> tuple[str, ...]:
    key = title.strip().casefold()
    return _WINDOW_TITLE_ALIASES.get(key, (key,))


def _compact_window_text(text: str) -> str:
    return "".join(char for char in text.casefold() if char.isalnum())
