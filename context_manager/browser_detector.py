from __future__ import annotations

import json
import logging
import urllib.request
import urllib.error
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class BrowserTab:
    id: int
    title: str
    url: str
    active: bool
    window_id: int


@dataclass
class BrowserInfo:
    name: str
    display_name: str
    process_name: str
    running: bool
    debug_port: int | None = None


@dataclass
class BrowserTabMatch:
    browser: BrowserInfo
    tab: BrowserTab


@dataclass
class ChromeState:
    running: bool
    windows: list[list[BrowserTab]]
    active_tab: BrowserTab | None = None
    debug_port: int = 0


_BROWSER_DEFS: list[BrowserInfo] = [
    BrowserInfo("chrome", "Chrome", "chrome.exe", running=False),
    BrowserInfo("msedge", "Microsoft Edge", "msedge.exe", running=False),
    BrowserInfo("firefox", "Firefox", "firefox.exe", running=False),
    BrowserInfo("brave", "Brave", "brave.exe", running=False),
    BrowserInfo("opera", "Opera", "opera.exe", running=False),
    BrowserInfo("vivaldi", "Vivaldi", "vivaldi.exe", running=False),
]

_CDP_PORTS = [9222, 9223, 9224, 9225, 9226, 9227, 9228, 9229, 9230]

_DISPLAY_NAMES: dict[str, str] = {
    "chrome": "Chrome",
    "msedge": "Microsoft Edge",
    "firefox": "Firefox",
    "brave": "Brave",
    "opera": "Opera",
    "vivaldi": "Vivaldi",
}


class BrowserDetector:
    def __init__(self) -> None:
        self._cached_browsers: list[BrowserInfo] | None = None

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

    # ------------------------------------------------------------------
    # Multi-browser detection
    # ------------------------------------------------------------------

    def detect_all_browsers(self) -> list[BrowserInfo]:
        browsers: list[BrowserInfo] = []
        running_pids: dict[str, list[int]] = self._collect_running_browser_pids()

        for bdef in _BROWSER_DEFS:
            if bdef.process_name in running_pids:
                browsers.append(BrowserInfo(
                    name=bdef.name,
                    display_name=bdef.display_name,
                    process_name=bdef.process_name,
                    running=True,
                ))
            else:
                browsers.append(BrowserInfo(
                    name=bdef.name,
                    display_name=bdef.display_name,
                    process_name=bdef.process_name,
                    running=False,
                ))

        port_browser_map = self._identify_cdp_browsers()
        for b in browsers:
            if b.running and b.name in port_browser_map:
                b.debug_port = port_browser_map[b.name]

        self._cached_browsers = browsers
        return browsers

    def find_website_across_browsers(self, keyword: str) -> list[BrowserTabMatch]:
        results: list[BrowserTabMatch] = []
        browsers = self.detect_all_browsers()

        for b in browsers:
            if not b.running:
                continue

            if b.debug_port:
                tabs = self._list_tabs(b.debug_port)
                if tabs:
                    for tab_data in tabs:
                        tab = BrowserTab(
                            id=tab_data.get("id", 0),
                            title=tab_data.get("title", ""),
                            url=tab_data.get("url", ""),
                            active=tab_data.get("active", False),
                            window_id=tab_data.get("windowId", 0),
                        )
                        if self._tab_matches(tab, keyword):
                            results.append(BrowserTabMatch(browser=b, tab=tab))

            if b.name == "firefox" and not results:
                firefox_tabs = self._detect_firefox_tabs(keyword)
                results.extend(firefox_tabs)

        return results

    def find_website_by_url_or_title(self, site_key: str, site_url: str = "") -> list[BrowserTabMatch]:
        results: list[BrowserTabMatch] = []
        browsers = self.detect_all_browsers()

        for b in browsers:
            if not b.running:
                continue

            if b.debug_port:
                tabs = self._list_tabs(b.debug_port)
                if tabs:
                    for tab_data in tabs:
                        tab = BrowserTab(
                            id=tab_data.get("id", 0),
                            title=tab_data.get("title", ""),
                            url=tab_data.get("url", ""),
                            active=tab_data.get("active", False),
                            window_id=tab_data.get("windowId", 0),
                        )
                        url_lower = tab.url.casefold()
                        title_lower = tab.title.casefold()
                        site_key_lower = site_key.casefold()
                        if site_url:
                            site_url_lower = site_url.casefold()
                        else:
                            site_url_lower = ""

                        matched = False
                        if site_key_lower and site_key_lower in url_lower:
                            matched = True
                        if site_key_lower and site_key_lower in title_lower:
                            matched = True
                        if site_url_lower and site_url_lower in url_lower:
                            matched = True
                        if matched:
                            results.append(BrowserTabMatch(browser=b, tab=tab))

            if b.name == "firefox" and not any(m.browser.name == "firefox" for m in results):
                firefox_tabs = self._detect_firefox_tabs(site_key)
                results.extend(firefox_tabs)

        return results

    def activate_tab(self, port: int, tab_id: int) -> bool:
        try:
            url = f"http://127.0.0.1:{port}/json/activate/{tab_id}"
            resp = urllib.request.urlopen(url, timeout=2)
            return resp.status == 200
        except (urllib.error.URLError, TimeoutError) as exc:
            logger.warning("Failed to activate tab %d on port %d: %s", tab_id, port, exc)
            return False

    def get_browser_display_name(self, process_name: str) -> str:
        for bdef in _BROWSER_DEFS:
            if bdef.process_name.casefold() == process_name.casefold():
                return bdef.display_name
        return process_name.replace(".exe", "").title()

    def get_active_tab_across_browsers(self) -> BrowserTabMatch | None:
        browsers = self.detect_all_browsers()
        for b in browsers:
            if not b.running or not b.debug_port:
                continue
            tabs = self._list_tabs(b.debug_port)
            if not tabs:
                continue
            for tab_data in tabs:
                if tab_data.get("active", False):
                    tab = BrowserTab(
                        id=tab_data.get("id", 0),
                        title=tab_data.get("title", ""),
                        url=tab_data.get("url", ""),
                        active=True,
                        window_id=tab_data.get("windowId", 0),
                    )
                    return BrowserTabMatch(browser=b, tab=tab)
        return None

    def classify_tab_content(self, tab: BrowserTab) -> str:
        url_lower = tab.url.casefold()
        title_lower = tab.title.casefold()
        if not url_lower and not title_lower:
            return "empty"
        # Music services
        if "youtube music" in url_lower or "youtube music" in title_lower:
            return "music"
        if "spotify" in url_lower or "spotify" in title_lower:
            return "music"
        if "tidal" in url_lower or "pandora" in url_lower or "soundcloud" in url_lower:
            return "music"
        # Video (non-music YouTube)
        if "youtube.com/watch" in url_lower:
            return "video"
        if "netflix" in url_lower or "netflix" in title_lower:
            return "video"
        if "youtube.com" in url_lower:
            return "video"
        # Work content
        if "docs.google.com" in url_lower or "docs.google" in url_lower:
            return "document"
        if "sheets.google" in url_lower:
            return "document"
        if "forms.google" in url_lower:
            return "form"
        if "github.com" in url_lower and "/pull/" in url_lower:
            return "code_review"
        if "github.com" in url_lower or "gitlab" in url_lower or "bitbucket" in url_lower:
            return "coding"
        # Search
        if "google.com/search" in url_lower or "bing.com/search" in url_lower or "duckduckgo" in url_lower:
            return "search"
        if "youtube.com/results" in url_lower:
            return "search"
        # Web apps
        if "google.com" in url_lower or "maps.google" in url_lower or "mail.google" in url_lower:
            return "webapp"
        if "chatgpt" in url_lower or "chat.openai" in url_lower or "claude" in url_lower or "bard" in url_lower:
            return "chat"
        return "web"

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _collect_running_browser_pids(self) -> dict[str, list[int]]:
        import psutil
        result: dict[str, list[int]] = {}
        proc_names = set(b.process_name for b in _BROWSER_DEFS)
        try:
            for proc in psutil.process_iter(["name", "pid"]):
                try:
                    pname = proc.info.get("name", "")
                    if pname.casefold() in proc_names:
                        result.setdefault(pname.casefold(), []).append(proc.info["pid"])
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    continue
        except Exception:
            pass
        return result

    def _identify_cdp_browsers(self) -> dict[str, int]:
        port_map: dict[str, int] = {}
        for port in _CDP_PORTS:
            try:
                url = f"http://127.0.0.1:{port}/json/version"
                resp = urllib.request.urlopen(url, timeout=0.5)
                if resp.status != 200:
                    continue
                data = resp.read().decode("utf-8")
                info = json.loads(data)
                browser_str = info.get("Browser", "")
                browser_name = self._identify_browser_from_version(browser_str)
                if browser_name:
                    port_map[browser_name] = port
            except (urllib.error.URLError, json.JSONDecodeError, TimeoutError):
                continue
        return port_map

    def _identify_browser_from_version(self, version_str: str) -> str | None:
        lowered = version_str.casefold()
        if "edge" in lowered:
            return "msedge"
        if "brave" in lowered:
            return "brave"
        if "opera" in lowered or "opr" in lowered:
            return "opera"
        if "vivaldi" in lowered:
            return "vivaldi"
        if "chrome" in lowered:
            return "chrome"
        if "chromium" in lowered:
            return "chrome"
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
            logger.warning("Failed to list tabs on port %d: %s", port, exc)
            return None

    def _detect_firefox_tabs(self, keyword: str) -> list[BrowserTabMatch]:
        import pygetwindow as gw
        results: list[BrowserTabMatch] = []
        firefox_browser: BrowserInfo | None = None
        browsers = self._cached_browsers
        if not browsers:
            browsers = self.detect_all_browsers()
        for b in browsers:
            if b.name == "firefox" and b.running:
                firefox_browser = b
                break

        if not firefox_browser:
            return results

        key = keyword.casefold()
        window_index = 0
        tab_id = 1000
        try:
            for window in gw.getAllWindows():
                title = window.title.strip()
                if not title:
                    continue
                if "firefox" not in title.casefold():
                    continue
                if key in title.casefold():
                    results.append(BrowserTabMatch(
                        browser=firefox_browser,
                        tab=BrowserTab(
                            id=tab_id,
                            title=title,
                            url="",
                            active=window_index == 0,
                            window_id=window_index,
                        ),
                    ))
                    tab_id += 1
                window_index += 1
        except Exception:
            pass
        return results

    def _tab_matches(self, tab: BrowserTab, keyword: str) -> bool:
        kw = keyword.casefold()
        return kw in tab.url.casefold() or kw in tab.title.casefold()

    def _find_debug_port(self) -> int | None:
        for port in _CDP_PORTS:
            try:
                url = f"http://127.0.0.1:{port}/json/version"
                resp = urllib.request.urlopen(url, timeout=1)
                if resp.status == 200:
                    return port
            except (urllib.error.URLError, ConnectionRefusedError, TimeoutError):
                continue
        return None


