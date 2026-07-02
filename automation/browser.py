"""
automation/browser.py

Default-browser URL launcher.

This module does not automate browser internals. It only asks the
operating system to open a URL in the user's default browser.
"""

from __future__ import annotations

import time
from urllib.parse import quote_plus
import pyautogui

import automation.apps as apps
import automation.windows as windows


class BrowserOperationError(Exception):
    """Raised when browser URL launch fails."""


_KNOWN_URLS: dict[str, str] = {
    "google": "https://www.google.com",
    "youtube": "https://www.youtube.com",
    "github": "https://github.com",
    "chatgpt": "https://chatgpt.com",
    "gmail": "https://mail.google.com",
}

_SEARCH_URLS: dict[str, str] = {
    "google": "https://www.google.com/search?q={query}",
    "youtube": "https://www.youtube.com/results?search_query={query}",
    "github": "https://github.com/search?q={query}",
    "wikipedia": "https://en.wikipedia.org/w/index.php?search={query}",
    "stackoverflow": "https://stackoverflow.com/search?q={query}",
}


def open_url(url: str) -> bool:
    """Open a URL or known website name in Chrome."""
    normalized_url = _normalize_url(url)

    try:
        _open_in_chrome_tab(normalized_url)
    except Exception as exc:
        raise BrowserOperationError(
            f"Failed to open URL {normalized_url!r}: {exc}"
        ) from exc

    return True


def search(provider: str, query: str) -> bool:
    """Open a provider search URL in the default browser."""
    provider_key = provider.strip().casefold()
    template = _SEARCH_URLS.get(provider_key)
    if template is None:
        raise BrowserOperationError(f"Unsupported search provider: {provider!r}.")

    if not isinstance(query, str) or not query.strip():
        raise BrowserOperationError("Search query must be a non-empty string.")

    return open_url(template.format(query=quote_plus(query.strip())))


def new_tab() -> bool:
    """Open a new tab in the current browser window."""
    try:
        _ensure_chrome_window()
        pyautogui.hotkey("ctrl", "t")
        return True
    except Exception as exc:
        raise BrowserOperationError(f"Failed to open new tab: {exc}") from exc


def close_current_tab() -> bool:
    """Close the active tab in the current browser window."""
    try:
        _ensure_chrome_window()
        pyautogui.hotkey("ctrl", "w")
        return True
    except Exception as exc:
        raise BrowserOperationError(f"Failed to close current tab: {exc}") from exc


def close_all_tabs() -> bool:
    """Close the current browser window and all its tabs."""
    try:
        _ensure_chrome_window()
        pyautogui.hotkey("ctrl", "shift", "w")
        return True
    except Exception as exc:
        raise BrowserOperationError(f"Failed to close all tabs: {exc}") from exc


def close_other_tabs() -> bool:
    """Close all tabs except the current one."""
    try:
        _ensure_chrome_window()
        pyautogui.hotkey("alt", "e")
        pyautogui.press("o")
        return True
    except Exception as exc:
        raise BrowserOperationError(f"Failed to close other tabs: {exc}") from exc


def close_specific_tab(tab: int) -> bool:
    """Switch to a numbered tab and close it."""
    if not isinstance(tab, int) or not 1 <= tab <= 8:
        raise BrowserOperationError("Tab number must be an integer from 1 to 8.")
    try:
        _ensure_chrome_window()
        pyautogui.hotkey("ctrl", str(tab))
        pyautogui.hotkey("ctrl", "w")
        return True
    except Exception as exc:
        raise BrowserOperationError(f"Failed to close tab {tab}: {exc}") from exc


def switch_tab(tab: int | None = None) -> bool:
    """Switch to a numbered tab or the next tab when no number is provided."""
    if tab is None:
        return next_tab()
    if not isinstance(tab, int) or not 1 <= tab <= 8:
        raise BrowserOperationError("Tab number must be an integer from 1 to 8.")
    try:
        _ensure_chrome_window()
        pyautogui.hotkey("ctrl", str(tab))
        return True
    except Exception as exc:
        raise BrowserOperationError(f"Failed to switch to tab {tab}: {exc}") from exc


def next_tab() -> bool:
    """Switch to the next tab."""
    try:
        _ensure_chrome_window()
        pyautogui.hotkey("ctrl", "tab")
        return True
    except Exception as exc:
        raise BrowserOperationError(f"Failed to switch to next tab: {exc}") from exc


def previous_tab() -> bool:
    """Switch to the previous tab."""
    try:
        _ensure_chrome_window()
        pyautogui.hotkey("ctrl", "shift", "tab")
        return True
    except Exception as exc:
        raise BrowserOperationError(f"Failed to switch to previous tab: {exc}") from exc


def duplicate_tab() -> bool:
    """Duplicate the current tab."""
    try:
        _ensure_chrome_window()
        # This is a common trick, not a universal shortcut.
        pyautogui.hotkey("alt", "d")
        pyautogui.hotkey("alt", "enter")
        return True
    except Exception as exc:
        raise BrowserOperationError(f"Failed to duplicate tab: {exc}") from exc


def reopen_closed_tab() -> bool:
    """Reopen the last closed tab."""
    try:
        _ensure_chrome_window()
        pyautogui.hotkey("ctrl", "shift", "t")
        return True
    except Exception as exc:
        raise BrowserOperationError(f"Failed to reopen closed tab: {exc}") from exc


def refresh_page(hard: bool = False) -> bool:
    """Refresh the current page (hard refresh if specified)."""
    try:
        _ensure_chrome_window()
        if hard:
            pyautogui.hotkey("ctrl", "shift", "r")
        else:
            pyautogui.press("f5")
        return True
    except Exception as exc:
        raise BrowserOperationError(f"Failed to refresh page: {exc}") from exc


def reload() -> bool:
    """Reload the current page."""
    return refresh_page(hard=False)


def back() -> bool:
    """Navigate back in the active Chrome tab."""
    try:
        _ensure_chrome_window()
        pyautogui.hotkey("alt", "left")
        return True
    except Exception as exc:
        raise BrowserOperationError(f"Failed to navigate back: {exc}") from exc


def forward() -> bool:
    """Navigate forward in the active Chrome tab."""
    try:
        _ensure_chrome_window()
        pyautogui.hotkey("alt", "right")
        return True
    except Exception as exc:
        raise BrowserOperationError(f"Failed to navigate forward: {exc}") from exc


def _open_in_chrome_tab(url: str) -> None:
    _ensure_chrome_window()
    pyautogui.hotkey("ctrl", "t")
    pyautogui.write(url, interval=0)
    pyautogui.press("enter")


def _ensure_chrome_window() -> None:
    if not apps.is_running("chrome"):
        apps.open_app("chrome")
        time.sleep(1.0)

    focused = windows.focus_window("chrome")
    if not focused:
        raise BrowserOperationError("Chrome is running, but no Chrome window could be focused.")


def _normalize_url(url: str) -> str:
    if not isinstance(url, str) or not url.strip():
        raise BrowserOperationError("URL must be a non-empty string.")

    target = url.strip()
    key = target.casefold()
    if key in _KNOWN_URLS:
        return _KNOWN_URLS[key]

    if target.startswith(("http://", "https://")):
        return target

    if "." in target:
        return f"https://{target}"

    raise BrowserOperationError(
        f"Unsupported website {url!r}. Use a full URL or a known website name."
    )
