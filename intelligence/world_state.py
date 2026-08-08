"""
intelligence/world_state.py — continuously updated world state.

The World Model (``world_model.WorldModel``) polls applications, browser
tabs, files, system and media in the background. ``WorldStateService``
wraps it and enriches each snapshot on demand with the per-command
details the planner needs: focused window, per-browser windows, current
website, YouTube playback state, clipboard, mouse position, visible
dialogs and pending confirmations.

Thread safety
-------------
``WorldStateService.current()`` is safe to call from any thread. Heavy
detection results are cached for ``cache_ttl`` seconds to stop the
CDP/psutil calls from hammering the machine on rapid queries.
"""

from __future__ import annotations

import ctypes
import logging
import threading
import time
from dataclasses import dataclass, field
from typing import Any

from context_manager.browser_detector import BrowserDetector
from world_model import WorldModel

logger = logging.getLogger(__name__)

_BROWSER_PROCESS_NAMES = {
    "chrome": "chrome.exe",
    "msedge": "msedge.exe",
    "brave": "brave.exe",
    "opera": "opera.exe",
    "vivaldi": "vivaldi.exe",
    "firefox": "firefox.exe",
}


@dataclass(frozen=True)
class AppWindowState:
    """A single running window."""

    pid: int
    name: str
    window_title: str
    is_active: bool
    process_path: str = ""


@dataclass(frozen=True)
class BrowserWindowState:
    """A single browser window (a group of tabs)."""

    index: int
    tab_count: int
    active_tab_title: str = ""
    active_tab_url: str = ""


@dataclass(frozen=True)
class BrowserState:
    """Per-browser live state."""

    name: str
    display_name: str
    running: bool
    windows: list[BrowserWindowState] = field(default_factory=list)
    active_url: str | None = None
    active_website: str | None = None
    content: str = "web"
    playing: bool = False

    @property
    def window_count(self) -> int:
        return len(self.windows)


@dataclass(frozen=True)
class WorldState:
    """Immutable view of the computer used by the Intelligent Planner.

    Every field is optional/empty rather than erroring: a collector that
    fails (e.g. CDP not enabled) degrades to ``None``/``[]`` instead of
    crashing the planner.
    """

    timestamp: float
    applications: list[AppWindowState] = field(default_factory=list)
    focused_window: str | None = None
    browsers: dict[str, BrowserState] = field(default_factory=dict)
    active_website: str | None = None
    video_playing: bool = False
    clipboard: str = ""
    mouse_position: tuple[int, int] | None = None
    selected_text: str = ""
    visible_dialogs: list[str] = field(default_factory=list)
    pending_confirmations: list[str] = field(default_factory=list)

    # ── Convenience queries used by the planner ─────────────────────

    def app_running(self, app_name: str) -> bool:
        key = app_name.strip().casefold()
        if any(key in a.name.casefold() or key in a.window_title.casefold()
               for a in self.applications):
            return True
        return any(b.running and key in b.name.casefold() for b in self.browsers.values())

    def browser(self, name: str) -> BrowserState | None:
        return self.browsers.get(name.strip().casefold())

    def browser_windows(self, name: str) -> list[BrowserWindowState]:
        b = self.browser(name)
        return b.windows if b else []


class WorldStateService:
    """Continuously maintained world state with on-demand enrichment."""

    def __init__(
        self,
        world_model: WorldModel | None = None,
        context_manager: Any = None,
        browser_detector: BrowserDetector | None = None,
        cache_ttl: float = 1.0,
    ) -> None:
        self._model = world_model or WorldModel()
        self._context_manager = context_manager
        self._browser_detector = browser_detector or BrowserDetector()
        self._cache_ttl = cache_ttl
        self._lock = threading.Lock()
        self._cache: WorldState | None = None
        self._cache_at: float = 0.0

    # ── Lifecycle ────────────────────────────────────────────────────

    def start(self) -> None:
        self._model.start()

    def stop(self) -> None:
        self._model.stop()

    # ── Public query API ─────────────────────────────────────────────

    def current(self) -> WorldState:
        """Return the current world state (cached for ``cache_ttl``)."""
        with self._lock:
            now = time.monotonic()
            if self._cache is not None and now - self._cache_at < self._cache_ttl:
                return self._cache
            self._cache = self._build()
            self._cache_at = now
            return self._cache

    def snapshot(self) -> Any:
        return self._model.get_snapshot()

    # ── Snapshot builder ─────────────────────────────────────────────

    def _build(self) -> WorldState:
        base = self._model.get_snapshot()
        apps = [
            AppWindowState(
                pid=a.pid,
                name=a.name,
                window_title=a.window_title,
                is_active=a.is_active,
                process_path=a.process_path,
            )
            for a in base.applications
        ]
        focused = next(
            (a.window_title or a.name for a in apps if a.is_active),
            None,
        )

        browsers = self._build_browsers()
        video_playing = self._compute_video_playing(base, browsers)

        return WorldState(
            timestamp=time.time(),
            applications=apps,
            focused_window=focused,
            browsers=browsers,
            active_website=self._active_website(browsers),
            video_playing=video_playing,
            clipboard=(base.system.clipboard_text if base.system else "") or "",
            mouse_position=self._mouse_position(),
            selected_text=self._selected_text(),
            visible_dialogs=self._visible_dialogs(),
            pending_confirmations=self._pending_confirmations(),
        )

    def _build_browsers(self) -> dict[str, BrowserState]:
        """Build per-browser state from the (background-updated) World
        Model snapshot plus a fast window-title scan. Deliberately avoids
        synchronous CDP port scans on the hot path — those can take
        seconds when a port is dead."""
        state: dict[str, BrowserState] = {}
        base = self._model.get_snapshot()
        media_playing = base.media.is_playing if base.media else False
        frag = base.browser  # BrowserInfo(active_browser, tabs, active_url)

        window_titles = self._browser_window_titles()
        running_by_name = self._running_browsers(base, window_titles)
        names = list(_BROWSER_PROCESS_NAMES)

        for name in names:
            display = self._browser_detector.get_browser_display_name(
                _BROWSER_PROCESS_NAMES[name]
            )
            running = running_by_name.get(name, False)
            is_active_browser = (
                frag is not None
                and frag.active_browser is not None
                and frag.active_browser.casefold() == name.casefold()
            )
            active_url = frag.active_url if is_active_browser else None
            tabs = frag.tabs if is_active_browser else []

            if tabs:
                windows = [
                    BrowserWindowState(
                        index=i,
                        tab_count=1,
                        active_tab_title=t.title,
                        active_tab_url=t.url,
                    )
                    for i, t in enumerate(tabs)
                ]
            else:
                windows = [
                    BrowserWindowState(index=i, tab_count=1, active_tab_title=title)
                    for i, title in enumerate(window_titles.get(name, []))
                ]

            content = "web"
            playing = False
            if active_url:
                content = self._browser_detector.classify_tab_content(
                    self._tab_from_url(active_url)
                )
                playing = self._tab_playing(active_url, media_playing)

            state[name] = BrowserState(
                name=name,
                display_name=display,
                running=running,
                windows=windows,
                active_url=active_url,
                active_website=self._website_from_url(active_url or ""),
                content=content,
                playing=playing,
            )
        return state

    # ── Individual collectors ────────────────────────────────────────

    @staticmethod
    def _running_browsers(base: Any, window_titles: dict[str, list[str]]) -> dict[str, bool]:
        running: dict[str, bool] = {name: False for name in _BROWSER_PROCESS_NAMES}
        for name in running:
            if window_titles.get(name):
                running[name] = True
        frag = base.browser
        if frag is not None and frag.active_browser:
            key = frag.active_browser.casefold()
            if key in running:
                running[key] = True
        for app in base.applications:
            name_lower = app.name.casefold()
            title_lower = app.window_title.casefold()
            for name, proc in _BROWSER_PROCESS_NAMES.items():
                proc_stem = proc.replace(".exe", "")
                if (
                    name_lower == proc
                    or proc_stem in name_lower
                    or proc_stem in title_lower
                ):
                    running[name] = True
        return running

    def _browser_window_titles(self) -> dict[str, list[str]]:
        import pygetwindow as gw

        titles: dict[str, list[str]] = {name: [] for name in _BROWSER_PROCESS_NAMES}
        try:
            for window in gw.getAllWindows():
                title = window.title.strip()
                if not title or not window.visible:
                    continue
                for name, proc in _BROWSER_PROCESS_NAMES.items():
                    if proc.replace(".exe", "") in title.casefold():
                        titles[name].append(title)
        except Exception as exc:
            logger.debug("WorldState: window title scan failed: %s", exc)
        return titles

    @staticmethod
    def _tab_from_url(url: str) -> Any:
        from context_manager.browser_detector import BrowserTab
        return BrowserTab(id=0, title="", url=url, active=True, window_id=0)

    @staticmethod
    def _tab_playing(url: str, media_playing: bool) -> bool:
        lower = url.casefold()
        if media_playing:
            return True
        if "youtube.com/watch" in lower or "youtube.com" in lower:
            return True
        if "youtube music" in lower or "spotify" in lower or "netflix" in lower:
            return True
        return False

    @staticmethod
    def _website_from_url(url: str) -> str | None:
        if not url:
            return None
        lower = url.casefold()
        if "youtube.com" in lower or "youtu.be" in lower:
            return "youtube"
        if "google.com" in lower:
            return "google"
        if "netflix.com" in lower:
            return "netflix"
        if "spotify.com" in lower:
            return "spotify"
        from urllib.parse import urlparse
        try:
            host = urlparse(url).netloc
            return host.replace("www.", "").split(".")[0] if host else None
        except Exception:
            return None

    def _active_website(self, browsers: dict[str, BrowserState]) -> str | None:
        for b in browsers.values():
            if b.active_website:
                return b.active_website
        return None

    @staticmethod
    def _compute_video_playing(base: Any, browsers: dict[str, BrowserState]) -> bool:
        if base.media is not None and base.media.is_playing:
            return True
        for b in browsers.values():
            if b.playing:
                return True
        return False

    @staticmethod
    def _mouse_position() -> tuple[int, int] | None:
        try:
            user32 = ctypes.windll.user32
            pt = ctypes.wintypes.POINT() if hasattr(ctypes, "wintypes") else None
            if pt is None:
                import ctypes.wintypes
                pt = ctypes.wintypes.POINT()
            user32.GetCursorPos(ctypes.byref(pt))
            return (pt.x, pt.y)
        except Exception:
            return None

    def _selected_text(self) -> str:
        # Best-effort: UI Automation selection is not available without
        # comtypes. Returns "" and degrades gracefully.
        return ""

    def _visible_dialogs(self) -> list[str]:
        try:
            from verification.dialog_detector import _DIALOG_KEYWORDS
        except Exception:
            return []
        import pygetwindow as gw

        found: list[str] = []
        keywords = set()
        for kws in _DIALOG_KEYWORDS.values():
            keywords.update(kws)
        try:
            for window in gw.getAllWindows():
                title = window.title.strip()
                if not title or not window.visible:
                    continue
                lowered = title.casefold()
                if any(kw in lowered for kw in keywords):
                    found.append(title)
        except Exception as exc:
            logger.debug("WorldState: dialog scan failed: %s", exc)
        return found

    def _pending_confirmations(self) -> list[str]:
        cm = self._context_manager
        if cm is None:
            return []
        try:
            if cm.has_pending_question():
                return [cm.get_pending_question()]
        except Exception:
            pass
        return []
