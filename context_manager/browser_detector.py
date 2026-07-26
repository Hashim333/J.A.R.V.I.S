from __future__ import annotations

import json
import logging
import urllib.request
import urllib.error
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class BrowserTab:
    id: int
    title: str
    url: str
    active: bool
    window_id: int


@dataclass
class ChromeState:
    running: bool
    windows: list[list[BrowserTab]]
    active_tab: BrowserTab | None = None
    debug_port: int = 0


class BrowserDetector:
    _DEFAULT_PORTS = [9222, 9223, 9224, 9225]

    def detect_chrome(self) -> ChromeState:
        port = self._find_debug_port()
        if not port:
            return ChromeState(running=False, windows=[])

        tabs = self._list_tabs(port)
        if tabs is None:
            return ChromeState(running=False, windows=[])

        windows: dict[int, list[BrowserTab]] = {}
        active_tab: BrowserTab | None = None

        for tab in tabs:
            wid = tab.get("windowId", 0)
            tid = tab.get("id", 0)
            title = tab.get("title", "")
            url = tab.get("url", "")
            active = tab.get("active", False)
            bt = BrowserTab(id=tid, title=title, url=url, active=active, window_id=wid)
            windows.setdefault(wid, []).append(bt)
            if active:
                active_tab = bt

        return ChromeState(
            running=True,
            windows=list(windows.values()),
            active_tab=active_tab,
            debug_port=port,
        )

    def find_tab_by_url(self, url_substring: str) -> BrowserTab | None:
        state = self.detect_chrome()
        if not state.running:
            return None
        target = url_substring.casefold()
        for win in state.windows:
            for tab in win:
                if target in tab.url.casefold() or target in tab.title.casefold():
                    return tab
        return None

    def find_tab_by_title(self, title_substring: str) -> BrowserTab | None:
        state = self.detect_chrome()
        if not state.running:
            return None
        target = title_substring.casefold()
        for win in state.windows:
            for tab in win:
                if target in tab.title.casefold() or target in tab.url.casefold():
                    return tab
        return None

    def _find_debug_port(self) -> int | None:
        for port in self._DEFAULT_PORTS:
            try:
                url = f"http://127.0.0.1:{port}/json/version"
                resp = urllib.request.urlopen(url, timeout=1)
                if resp.status == 200:
                    return port
            except (urllib.error.URLError, ConnectionRefusedError, TimeoutError):
                continue
        return None

    def _list_tabs(self, port: int) -> list[dict] | None:
        try:
            url = f"http://127.0.0.1:{port}/json"
            resp = urllib.request.urlopen(url, timeout=2)
            if resp.status != 200:
                return None
            data = resp.read().decode("utf-8")
            return json.loads(data)
        except (urllib.error.URLError, json.JSONDecodeError, TimeoutError) as exc:
            logger.warning("Failed to list Chrome tabs on port %d: %s", port, exc)
            return None
