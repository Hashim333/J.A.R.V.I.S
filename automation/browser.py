"""
automation/browser.py

Default-browser URL launcher.

This module does not automate browser internals. It only asks the
operating system to open a URL in the user's default browser.
"""

from __future__ import annotations

import webbrowser
from urllib.parse import quote_plus
import pyautogui


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
    """Open a URL or known website name in the default browser."""
    normalized_url = _normalize_url(url)

    try:
        opened = webbrowser.open(normalized_url, new=2, autoraise=True)
    except Exception as exc:
        raise BrowserOperationError(
            f"Failed to open URL {normalized_url!r}: {exc}"
        ) from exc

    if not opened:
        raise BrowserOperationError(f"Default browser refused URL {normalized_url!r}.")

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
        pyautogui.hotkey("ctrl", "t")
        return True
    except Exception as exc:
        raise BrowserOperationError(f"Failed to open new tab: {exc}") from exc


def close_current_tab() -> bool:
    """Close the active tab in the current browser window."""
    try:
        pyautogui.hotkey("ctrl", "w")
        return True
    except Exception as exc:
        raise BrowserOperationError(f"Failed to close current tab: {exc}") from exc


def close_all_tabs() -> bool:
    """Close the current browser window and all its tabs."""
    try:
        pyautogui.hotkey("ctrl", "shift", "w")
        return True
    except Exception as exc:
        raise BrowserOperationError(f"Failed to close all tabs: {exc}") from exc


def next_tab() -> bool:
    """Switch to the next tab."""
    try:
        pyautogui.hotkey("ctrl", "tab")
        return True
    except Exception as exc:
        raise BrowserOperationError(f"Failed to switch to next tab: {exc}") from exc


def previous_tab() -> bool:
    """Switch to the previous tab."""
    try:
        pyautogui.hotkey("ctrl", "shift", "tab")
        return True
    except Exception as exc:
        raise BrowserOperationError(f"Failed to switch to previous tab: {exc}") from exc


def duplicate_tab() -> bool:
    """Duplicate the current tab."""
    try:
        # This is a common trick, not a universal shortcut.
        pyautogui.hotkey("alt", "d")
        pyautogui.hotkey("alt", "enter")
        return True
    except Exception as exc:
        raise BrowserOperationError(f"Failed to duplicate tab: {exc}") from exc


def reopen_closed_tab() -> bool:
    """Reopen the last closed tab."""
    try:
        pyautogui.hotkey("ctrl", "shift", "t")
        return True
    except Exception as exc:
        raise BrowserOperationError(f"Failed to reopen closed tab: {exc}") from exc


def refresh_page(hard: bool = False) -> bool:
    """Refresh the current page (hard refresh if specified)."""
    try:
        if hard:
            pyautogui.hotkey("ctrl", "shift", "r")
        else:
            pyautogui.press("f5")
        return True
    except Exception as exc:
        raise BrowserOperationError(f"Failed to refresh page: {exc}") from exc


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
