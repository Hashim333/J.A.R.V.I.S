"""
world_model/collectors/browser.py — Browser state collector.

Collects:
  - Active browser identification
  - Open tabs (from window titles)
  - Active URL (heuristic from title / CDP where available)

Platform notes:
  - Window titles are used as a fallback on all platforms
  - Chrome/Edge DevTools Protocol (CDP) is attempted for precise URL data
"""

from __future__ import annotations

import json
import logging
import socket
import time
from typing import Any

import psutil

from world_model.collectors import BaseCollector, logger

_KNOWN_BROWSERS = {
    "chrome.exe", "msedge.exe", "firefox.exe", "opera.exe",
    "brave.exe", "vivaldi.exe", "iexplore.exe",
}

_BROWSER_CDP_PORTS = {
    "chrome.exe": 9222,
    "msedge.exe": 9222,
    "brave.exe": 9222,
    "vivaldi.exe": 9222,
}


class BrowserCollector(BaseCollector):
    """Collects active browser info and open tabs."""

    def __init__(self, poll_interval: float = 3.0) -> None:
        super().__init__(poll_interval)

    def collect(self) -> dict[str, Any]:
        try:
            return self._collect()
        except Exception as exc:
            logger.warning("BrowserCollector: %s", exc)
            return {}

    def _collect(self) -> dict[str, Any]:
        browser_name, browser_pid = self._find_active_browser()
        if browser_name is None:
            return {"browser": None}

        # Try CDP for precise URL/tab info
        tabs = []
        active_url = None
        cdp_port = _BROWSER_CDP_PORTS.get(browser_name)
        if cdp_port is not None:
            try:
                tabs, active_url = self._cdp_tabs(cdp_port)
            except Exception:
                pass  # fall back to window title heuristic

        # Fallback: extract from window titles
        if not tabs:
            fallback_title = self._get_browser_window_title(browser_pid)
            if fallback_title:
                tabs = [{"title": fallback_title, "url": ""}]
                active_url = self._extract_url_from_title(fallback_title)

        return {
            "browser": {
                "active_browser": browser_name.replace(".exe", ""),
                "tabs": tabs,
                "active_url": active_url,
            },
        }

    # ── Browser detection ──────────────────────────────────────────

    def _find_active_browser(self) -> tuple[str | None, int | None]:
        """Return (exe_name, pid) of the foreground browser, or (None, None)."""
        active_pid = self._get_active_window_pid()
        if active_pid == 0:
            return None, None

        try:
            proc = psutil.Process(active_pid)
            exe = proc.name().lower()
            if exe in _KNOWN_BROWSERS:
                return exe, active_pid
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass

        # Also scan all running browser processes
        for proc in psutil.process_iter(["pid", "name"]):
            try:
                if proc.info["name"] and proc.info["name"].lower() in _KNOWN_BROWSERS:
                    return proc.info["name"].lower(), proc.info["pid"]
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue

        return None, None

    # ── CDP (Chrome DevTools Protocol) ──────────────────────────────

    def _cdp_tabs(self, port: int) -> tuple[list[dict], str | None]:
        """Query Chrome/Edge DevTools for open tabs and active URL."""
        try:
            import requests
            resp = requests.get(
                f"http://127.0.0.1:{port}/json",
                timeout=2.0,
            )
            if resp.status_code != 200:
                return [], None
            tabs_data = resp.json()
            tabs = []
            active_url = None
            for t in tabs_data:
                title = t.get("title", "")
                url = t.get("url", "")
                if title:
                    tabs.append({"title": title, "url": url})
                if t.get("active"):
                    active_url = url
            return tabs, active_url
        except Exception:
            return [], None

    # ── Window-title fallback ───────────────────────────────────────

    def _get_browser_window_title(self, pid: int) -> str | None:
        """Return the most descriptive visible window title for a PID."""
        try:
            import ctypes
            from ctypes import wintypes
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
                return max(titles, key=len)
            return None
        except Exception:
            return None

    @staticmethod
    def _extract_url_from_title(title: str) -> str | None:
        """Attempt to extract a URL from a browser tab title.

        Browsers typically format titles as:  "Page Title - Google Chrome"
        or the URL itself for pages without a meta title.
        """
        import re
        # Try to find http/https URL in the title
        url_match = re.search(r"https?://[^\s-]+", title)
        if url_match:
            return url_match.group(0)
        return None

    # ── Windows helper ─────────────────────────────────────────────

    @staticmethod
    def _get_active_window_pid() -> int:
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
