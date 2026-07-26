"""
automation/browser.py

Context-aware browser automation.  Before opening a new tab this module
checks whether the target site is already open in an existing Chrome
tab and reuses it.

Supported sites (auto-detect + search-on-site):
  google, youtube, github, gmail, chatgpt,
  facebook, instagram, linkedin
"""

from __future__ import annotations

import logging
import time
from typing import Callable
from urllib.parse import quote_plus

import pyautogui
import pygetwindow as gw

import automation.apps as apps
import automation.windows as windows

logger = logging.getLogger(__name__)


class BrowserOperationError(Exception):
    """Raised when a browser operation fails."""


# ---------------------------------------------------------------------------
# Known websites
# ---------------------------------------------------------------------------

_KNOWN_URLS: dict[str, str] = {
    "google": "https://www.google.com",
    "youtube": "https://www.youtube.com",
    "github": "https://github.com",
    "chatgpt": "https://chatgpt.com",
    "gmail": "https://mail.google.com",
    "facebook": "https://www.facebook.com",
    "instagram": "https://www.instagram.com",
    "linkedin": "https://www.linkedin.com",
}

_SEARCH_URLS: dict[str, str] = {
    "google": "https://www.google.com/search?q={query}",
    "youtube": "https://www.youtube.com/results?search_query={query}",
    "github": "https://github.com/search?q={query}",
    "wikipedia": "https://en.wikipedia.org/w/index.php?search={query}",
    "stackoverflow": "https://stackoverflow.com/search?q={query}",
    "gmail": "https://mail.google.com/mail/u/0/#search/{query}",
    "facebook": "https://www.facebook.com/search/top/?q={query}",
    "instagram": "https://www.instagram.com/explore/search/keyword/?q={query}",
    "linkedin": "https://www.linkedin.com/search/results/all/?keywords={query}",
}

# Per-site search strategies (for on-page search bar interaction)
_SITE_SEARCH_CONFIG: dict[str, dict] = {
    "youtube": {
        "shortcut": "/",
        "wait_after_nav": 1.5,
    },
    "github": {
        "shortcut": "s",
        "wait_after_nav": 1.0,
    },
    "google": {
        "shortcut": None,
        "wait_after_nav": 0.5,
    },
    "gmail": {"shortcut": None, "wait_after_nav": 1.0},
    "chatgpt": {"shortcut": None, "wait_after_nav": 1.0},
    "facebook": {"shortcut": None, "wait_after_nav": 1.5},
    "instagram": {"shortcut": None, "wait_after_nav": 1.5},
    "linkedin": {"shortcut": None, "wait_after_nav": 1.0},
}


# ---------------------------------------------------------------------------
# Tab detection
# ---------------------------------------------------------------------------


def _is_site_open(site_name: str) -> bool:
    """Return True if *site_name* appears in any Chrome window title."""
    site_key = site_name.strip().casefold()
    try:
        for window in gw.getAllWindows():
            title = window.title.strip()
            if not title or "chrome" not in title.casefold():
                continue
            if site_key in title.casefold():
                return True
    except Exception:
        pass
    return False


def _focus_chrome(site_name: str | None = None) -> None:
    """Ensure Chrome is focused, optionally targeting a window with *site_name*."""
    if not apps.is_running("chrome"):
        apps.open_app("chrome")
        time.sleep(1.0)

    if site_name:
        site_key = site_name.strip().casefold()
        try:
            for window in gw.getAllWindows():
                title = window.title.strip().casefold()
                if not title or "chrome" not in title:
                    continue
                if site_key in title:
                    if window.isMinimized:
                        window.restore()
                    window.activate()
                    return
        except Exception:
            pass

    focused = windows.focus_window("chrome")
    if not focused:
        raise BrowserOperationError("Chrome is running but no window could be focused.")


# ---------------------------------------------------------------------------
# Page interaction
# ---------------------------------------------------------------------------


def _navigate_current_tab(url: str) -> None:
    """Navigate the *current* browser tab to *url* (Ctrl+L then type+Enter)."""
    time.sleep(0.15)
    pyautogui.hotkey("ctrl", "l")
    time.sleep(0.1)
    pyautogui.write(url, interval=0)
    pyautogui.press("enter")


def _search_via_shortcut(site_name: str, query: str) -> None:
    """Use an on-page keyboard shortcut to search."""
    cfg = _SITE_SEARCH_CONFIG.get(site_name.strip().casefold())
    shortcut = (cfg or {}).get("shortcut")
    if shortcut:
        time.sleep(0.3)
        pyautogui.press(shortcut)
        time.sleep(0.2)
        pyautogui.write(query, interval=0)
        pyautogui.press("enter")


def _wait_after_nav(site_name: str) -> None:
    """Pause enough for *site_name* to load after navigation."""
    cfg = _SITE_SEARCH_CONFIG.get(site_name.strip().casefold())
    wait = (cfg or {}).get("wait_after_nav", 0.5)
    time.sleep(wait)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def open_url(url: str) -> bool:
    """Open a URL.  If the site is already open in a Chrome tab, focus it.

    Falls back to a new tab when the site is not open.
    """
    normalized = _normalize_url(url)

    known_site = _normalized_to_site_name(normalized)
    if known_site and _is_site_open(known_site):
        logger.info("Tab reuse: %r already open — focusing", known_site)
        _focus_chrome(known_site)
        return True

    logger.info("Opening new tab: %s", normalized)
    _focus_chrome()
    _navigate_current_tab(normalized)
    return True


def search(provider: str, query: str) -> bool:
    """Search *provider* for *query*.

    If the site is already open the current tab is reused (no duplicate
    tabs).  If the site supports an on-page keyboard shortcut it is used;
    otherwise a search-URL is navigated to.
    """
    provider_key = provider.strip().casefold()
    site_open = _is_site_open(provider_key)

    template = _SEARCH_URLS.get(provider_key)
    if not template:
        raise BrowserOperationError(f"Unsupported search provider: {provider!r}.")
    if not isinstance(query, str) or not query.strip():
        raise BrowserOperationError("Search query must be a non-empty string.")

    search_url = template.format(query=quote_plus(query.strip()))
    cfg = _SITE_SEARCH_CONFIG.get(provider_key, {})
    shortcut = cfg.get("shortcut")

    if site_open:
        logger.info("Tab reuse for search: %r already open — reusing tab", provider_key)
        _focus_chrome(provider_key)

        if shortcut:
            _search_via_shortcut(provider_key, query)
        else:
            _navigate_current_tab(search_url)
        return True

    logger.info("Opening new tab for search: %s", search_url)
    _focus_chrome()
    _navigate_current_tab(search_url)
    _wait_after_nav(provider_key)

    if shortcut:
        _search_via_shortcut(provider_key, query)

    return True


# ---------------------------------------------------------------------------
# Tab management (unchanged API)
# ---------------------------------------------------------------------------


def new_tab() -> bool:
    """Open a new tab."""
    _ensure_chrome_window()
    pyautogui.hotkey("ctrl", "t")
    return True


def close_current_tab() -> bool:
    """Close the active tab."""
    _ensure_chrome_window()
    pyautogui.hotkey("ctrl", "w")
    return True


def close_all_tabs() -> bool:
    """Close the current window and all its tabs."""
    _ensure_chrome_window()
    pyautogui.hotkey("ctrl", "shift", "w")
    return True


def close_other_tabs() -> bool:
    _ensure_chrome_window()
    pyautogui.hotkey("alt", "e")
    pyautogui.press("o")
    return True


def close_specific_tab(tab: int) -> bool:
    if not isinstance(tab, int) or not 1 <= tab <= 8:
        raise BrowserOperationError("Tab number must be 1-8.")
    _ensure_chrome_window()
    pyautogui.hotkey("ctrl", str(tab))
    pyautogui.hotkey("ctrl", "w")
    return True


def switch_tab(tab: int | None = None) -> bool:
    if tab is None:
        return next_tab()
    if not isinstance(tab, int) or not 1 <= tab <= 8:
        raise BrowserOperationError("Tab number must be 1-8.")
    _ensure_chrome_window()
    pyautogui.hotkey("ctrl", str(tab))
    return True


def next_tab() -> bool:
    _ensure_chrome_window()
    pyautogui.hotkey("ctrl", "tab")
    return True


def previous_tab() -> bool:
    _ensure_chrome_window()
    pyautogui.hotkey("ctrl", "shift", "tab")
    return True


def duplicate_tab() -> bool:
    _ensure_chrome_window()
    pyautogui.hotkey("alt", "d")
    pyautogui.hotkey("alt", "enter")
    return True


def reopen_closed_tab() -> bool:
    _ensure_chrome_window()
    pyautogui.hotkey("ctrl", "shift", "t")
    return True


def refresh_page(hard: bool = False) -> bool:
    _ensure_chrome_window()
    if hard:
        pyautogui.hotkey("ctrl", "shift", "r")
    else:
        pyautogui.press("f5")
    return True


def reload() -> bool:
    return refresh_page(hard=False)


def back() -> bool:
    _ensure_chrome_window()
    pyautogui.hotkey("alt", "left")
    return True


def forward() -> bool:
    _ensure_chrome_window()
    pyautogui.hotkey("alt", "right")
    return True


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _ensure_chrome_window() -> None:
    if not apps.is_running("chrome"):
        apps.open_app("chrome")
        time.sleep(1.0)
    focused = windows.focus_window("chrome")
    if not focused:
        raise BrowserOperationError("Chrome is running but no window could be focused.")


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


def _normalized_to_site_name(normalized_url: str) -> str | None:
    """Reverse-lookup a normalized URL to its known site name."""
    for name, site_url in _KNOWN_URLS.items():
        if normalized_url == site_url:
            return name
    return None
