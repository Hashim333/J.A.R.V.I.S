"""
automation/browser_manager.py

Dedicated browser manager that consolidates browser launch, URL
navigation, search, and Chrome profile management.

Replaces ad-hoc browser logic spread across apps.py and browser.py.
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
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

_KNOWN_WEBSITES: dict[str, str] = {
    "google": "https://www.google.com",
    "youtube": "https://www.youtube.com",
    "github": "https://github.com",
    "chatgpt": "https://chatgpt.com",
    "chat gpt": "https://chatgpt.com",
    "gmail": "https://mail.google.com",
    "stackoverflow": "https://stackoverflow.com",
    "stack overflow": "https://stackoverflow.com",
    "reddit": "https://www.reddit.com",
    "wikipedia": "https://www.wikipedia.org",
    "twitter": "https://twitter.com",
    "facebook": "https://www.facebook.com",
    "instagram": "https://www.instagram.com",
    "linkedin": "https://www.linkedin.com",
    "amazon": "https://www.amazon.com",
    "netflix": "https://www.netflix.com",
    "spotify": "https://open.spotify.com",
    "whatsapp": "https://web.whatsapp.com",
    "maps": "https://maps.google.com",
    "google maps": "https://maps.google.com",
    "drive": "https://drive.google.com",
    "google drive": "https://drive.google.com",
    "docs": "https://docs.google.com",
    "google docs": "https://docs.google.com",
    "calendar": "https://calendar.google.com",
    "google calendar": "https://calendar.google.com",
    "meet": "https://meet.google.com",
    "google meet": "https://meet.google.com",
    "bing": "https://www.bing.com",
    "duckduckgo": "https://duckduckgo.com",
    "yahoo": "https://www.yahoo.com",
    "ebay": "https://www.ebay.com",
    "cnn": "https://www.cnn.com",
    "bbc": "https://www.bbc.com",
    "nytimes": "https://www.nytimes.com",
}

_SEARCH_URLS: dict[str, str] = {
    "google": "https://www.google.com/search?q={query}",
    "youtube": "https://www.youtube.com/results?search_query={query}",
    "github": "https://github.com/search?q={query}",
    "wikipedia": "https://en.wikipedia.org/w/index.php?search={query}",
    "stackoverflow": "https://stackoverflow.com/search?q={query}",
    "bing": "https://www.bing.com/search?q={query}",
    "duckduckgo": "https://duckduckgo.com/?q={query}",
    "reddit": "https://www.reddit.com/search/?q={query}",
}

# Browser preference — currently Chrome only but can be extended.
# The first entry is the default browser.
_SUPPORTED_BROWSERS = ("chrome", "edge")


# ---------------------------------------------------------------------------
# Chrome profile
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ChromeProfile:
    directory: str
    display_name: str


# User-configurable profile aliases: phrase -> profile directory substring.
# "work" matches any profile whose display_name or directory contains "work".
_DEFAULT_PROFILE_ALIASES: dict[str, str] = {
    "default": "Default",
    "my profile": "Default",
    "mine": "Default",
    "personal": "Default",
    "work": "Profile 1",
    "gaming": "Profile 2",
    "school": "Profile 3",
}


# ---------------------------------------------------------------------------
# BrowserManager
# ---------------------------------------------------------------------------


class BrowserManager:
    """
    High-level browser operations.

    Manages Chrome profiles, URL launching, search, and window focus.
    """

    def __init__(self, profile_aliases: dict[str, str] | None = None) -> None:
        self._profile_aliases = dict(_DEFAULT_PROFILE_ALIASES)
        if profile_aliases:
            for phrase, directory in profile_aliases.items():
                self._profile_aliases[phrase.strip().casefold()] = directory

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def open_browser(
        self,
        browser: str = "chrome",
        profile: str | None = None,
        voice_input: Callable[[], str | None] | None = None,
    ) -> dict:
        """
        Open a browser, optionally with a specific Chrome profile.

        If the browser is already running it is focused instead of
        launching a new instance (unless a profile switch is needed).
        """
        browser = self._resolve_browser(browser)

        if browser != "chrome" or profile is None:
            return self._launch_browser(browser, profile, voice_input)

        resolved = self._resolve_profile(profile, voice_input)
        if resolved is None:
            return {"success": False, "message": "Could not resolve Chrome profile."}

        # If Chrome is already running with this profile, focus it.
        focused = self._focus_chrome_profile(resolved.directory)
        if focused:
            return {
                "success": True,
                "message": f"Chrome ({resolved.display_name}) is already running. Brought to foreground.",
                "details": {"action": "focused", "profile": resolved.directory},
            }

        # Launch Chrome with the target profile.
        return self._launch_browser("chrome", resolved.directory, voice_input)

    def open_url(self, url: str) -> dict:
        """Open a URL in the browser. Accepts known website names or full URLs."""
        target = self._normalize_url(url)
        if target is None:
            return {
                "success": False,
                "message": f"Unsupported website: {url!r}.",
            }

        try:
            self._ensure_browser_window("chrome")
            pyautogui.hotkey("ctrl", "t")
            time.sleep(0.15)
            pyautogui.write(target, interval=0)
            pyautogui.press("enter")
            return {
                "success": True,
                "message": f"Opened {target}.",
                "details": {"url": target},
            }
        except Exception as exc:
            logger.error("Failed to open URL %r: %s", target, exc)
            return {
                "success": False,
                "message": f"Could not open {url}: {exc}",
            }

    def search(self, query: str, provider: str = "google") -> dict:
        """Search a provider for a query."""
        provider_key = provider.strip().casefold()
        template = _SEARCH_URLS.get(provider_key)
        if template is None:
            return {
                "success": False,
                "message": f"Unsupported search provider: {provider!r}.",
            }

        if not query.strip():
            return {
                "success": False,
                "message": "Search query must not be empty.",
            }

        url = template.format(query=quote_plus(query.strip()))
        result = self.open_url(url)
        if result["success"]:
            result["message"] = f"Searched {provider} for '{query}'."
        return result

    def focus_existing_window(self, browser: str = "chrome") -> bool:
        """Focus an existing browser window.  Returns True if successful."""
        browser = self._resolve_browser(browser)
        try:
            return bool(windows.focus_window(browser))
        except Exception:
            return False

    def is_known_website(self, name: str) -> str | None:
        """Return the URL for a known website name, or None."""
        key = name.strip().casefold()
        return _KNOWN_WEBSITES.get(key)

    def list_known_websites(self) -> list[str]:
        """Return the list of known website short names."""
        return sorted(_KNOWN_WEBSITES)

    # ------------------------------------------------------------------
    # Chrome profile helpers
    # ------------------------------------------------------------------

    def _chrome_user_data_dir(self) -> Path:
        local_app_data = os.environ.get("LOCALAPPDATA")
        candidates: list[Path] = []
        if local_app_data:
            candidates.append(Path(local_app_data) / "Google" / "Chrome" / "User Data")
        candidates.append(
            Path.home() / "AppData" / "Local" / "Google" / "Chrome" / "User Data"
        )
        for candidate in candidates:
            if candidate.exists():
                return candidate
        raise BrowserOperationError(
            "Could not locate Chrome User Data directory."
        )

    def _chrome_profiles(self) -> list[ChromeProfile]:
        user_data_dir = self._chrome_user_data_dir()
        local_state_path = user_data_dir / "Local State"
        if not local_state_path.exists():
            raise BrowserOperationError(
                f"Could not find Chrome Local State at {local_state_path}."
            )

        try:
            with local_state_path.open("r", encoding="utf-8") as f:
                local_state = json.load(f)
        except (json.JSONDecodeError, OSError) as exc:
            raise BrowserOperationError(
                f"Could not read Chrome Local State: {exc}"
            ) from exc

        info_cache = local_state.get("profile", {}).get("info_cache", {})
        if not isinstance(info_cache, dict) or not info_cache:
            raise BrowserOperationError("No Chrome profiles found.")

        profiles: list[ChromeProfile] = []
        for directory, data in info_cache.items():
            if not isinstance(directory, str):
                continue
            if not isinstance(data, dict):
                data = {}
            display_name = (
                data.get("name")
                or data.get("shortcut_name")
                or data.get("gaia_name")
                or directory
            )
            profiles.append(ChromeProfile(directory=directory, display_name=str(display_name)))

        if not profiles:
            raise BrowserOperationError("No usable Chrome profiles found.")
        return profiles

    def _resolve_profile(
        self,
        profile_input: str,
        voice_input: Callable[[], str | None] | None = None,
    ) -> ChromeProfile | None:
        """Resolve a profile string to a ChromeProfile."""
        try:
            profiles = self._chrome_profiles()
        except BrowserOperationError:
            return None

        if not profile_input:
            return profiles[0] if profiles else None

        # Exact match on display name or directory
        key = profile_input.strip().casefold()
        for p in profiles:
            if p.display_name.casefold() == key or p.directory.casefold() == key:
                return p

        # Alias match — map alias to directory, then find the profile
        alias_dir = self._profile_aliases.get(key)
        if alias_dir:
            for p in profiles:
                if p.directory.casefold() == alias_dir.casefold():
                    return p

        # Fuzzy: profile directory contains the input
        for p in profiles:
            if key in p.directory.casefold() or key in p.display_name.casefold():
                return p

        # Number: "profile 2" → index 1 (0-based)
        if key.isdigit():
            idx = int(key) - 1
            if 0 <= idx < len(profiles):
                return profiles[idx]

        return None

    def _focus_chrome_profile(self, directory: str) -> bool:
        """Focus a Chrome window running with a specific profile directory."""
        try:
            for window in gw.getAllWindows():
                title = window.title.strip().casefold()
                if not title:
                    continue
                if "chrome" not in title:
                    continue
                if directory.casefold() in title:
                    if window.isMinimized:
                        window.restore()
                    window.activate()
                    return True
        except Exception:
            pass
        return False

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _resolve_browser(browser: str) -> str:
        """Normalize browser name or raise BrowserOperationError if unknown."""
        key = browser.strip().casefold()
        if key in ("google chrome", "chrome browser", "browser"):
            return "chrome"
        if key in ("microsoft edge", "ms edge", "edge browser"):
            return "edge"
        if key in _SUPPORTED_BROWSERS:
            return key
        raise BrowserOperationError(
            f"Unsupported browser: {browser!r}. Supported: {', '.join(_SUPPORTED_BROWSERS)}."
        )

    def _launch_browser(
        self,
        browser: str,
        profile: str | None,
        voice_input: Callable[[], str | None] | None,
    ) -> dict:
        """Launch a browser, optionally with a Chrome profile."""
        if browser == "chrome":
            extra_args = []
            if profile:
                extra_args = [f"--profile-directory={profile}"]
            try:
                apps._launch("chrome", extra_args)
                time.sleep(0.5)
                return {
                    "success": True,
                    "message": f"Chrome opened{' with profile '+profile if profile else ''}.",
                    "details": {"browser": "chrome", "profile": profile},
                }
            except Exception as exc:
                return {"success": False, "message": f"Could not launch Chrome: {exc}"}

        # Non-Chrome browsers — launch via apps
        try:
            apps._launch(browser)
            return {
                "success": True,
                "message": f"{browser} opened.",
                "details": {"browser": browser},
            }
        except Exception as exc:
            return {"success": False, "message": f"Could not launch {browser}: {exc}"}

    @staticmethod
    def _normalize_url(url: str) -> str | None:
        """Convert a short name or string to a full URL."""
        if not url or not url.strip():
            return None

        target = url.strip()
        key = target.casefold()

        if key in _KNOWN_WEBSITES:
            return _KNOWN_WEBSITES[key]

        if target.startswith(("http://", "https://")):
            return target

        if "." in target:
            return f"https://{target}"

        return None

    @staticmethod
    def _ensure_browser_window(browser: str) -> None:
        """Ensure a browser window is open and focused."""
        if not apps.is_running(browser):
            apps._launch(browser)
            time.sleep(1.0)

        focused = windows.focus_window(browser)
        if not focused:
            raise BrowserOperationError(
                f"{browser} is running but no window could be focused."
            )
