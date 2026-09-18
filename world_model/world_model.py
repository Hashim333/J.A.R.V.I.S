"""
world_model/world_model.py — World Model orchestrator.

Continuously maintains a structured representation of the computer's
current state by polling domain-specific collectors on a background
thread.  Consumers receive immutable ``WorldSnapshot`` objects.

Thread model
------------
- One background thread (``_loop``) drives all collectors sequentially.
- Each collector runs at its own ``poll_interval``.
- The current snapshot is protected by a ``threading.Lock`` — reads and
  writes are thread-safe.
- Collectors may internally use sub-threads or blocking I/O (WMI, psutil,
  Win32 API); none of that touches the UI thread.

Usage
-----
    from world_model import WorldModel

    wm = WorldModel()
    wm.start()

    # Later, from any thread:
    snapshot = wm.get_snapshot()
    print(snapshot.system.cpu_percent)
    print(snapshot.applications)

    wm.stop()
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Any

from world_model.collectors import BaseCollector
from world_model.collectors.applications import ApplicationsCollector
from world_model.collectors.browser import BrowserCollector
from world_model.collectors.files import FilesCollector
from world_model.collectors.media import MediaCollector
from world_model.collectors.system import SystemCollector
from world_model.model import (
    ApplicationInfo,
    BrowserInfo,
    BrowserTab,
    FileInfo,
    MediaInfo,
    SystemInfo,
    WorldSnapshot,
)

logger = logging.getLogger(__name__)


class WorldModel:
    """Orchestrates collectors and exposes a thread-safe query API.

    Public methods are safe to call from any thread.
    """

    def __init__(self, collectors: list[BaseCollector] | None = None) -> None:
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._snapshot: WorldSnapshot = WorldSnapshot.empty()

        # Default collector set — override by passing an explicit list
        self._collectors: list[BaseCollector] = (
            collectors if collectors is not None else [
                ApplicationsCollector(),
                BrowserCollector(),
                FilesCollector(),
                SystemCollector(),
                MediaCollector(),
            ]
        )

    # ── Lifecycle ─────────────────────────────────────────────────────

    def start(self) -> None:
        """Start the background collection loop."""
        if self._thread is not None and self._thread.is_alive():
            logger.warning("WorldModel: already running")
            return
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._loop, name="world-model", daemon=True,
        )
        self._thread.start()
        logger.info(
            "WorldModel: started with %d collectors", len(self._collectors),
        )

    def stop(self) -> None:
        """Signal the background loop to stop and wait for it.

        The loop only performs read-only collection and publishes under a
        lock, so abandoning a still-blocked collector after a bounded wait
        is safe (the thread is daemon and holds no resources that need
        releasing).
        """
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=2.0)
            if self._thread.is_alive():
                logger.warning("WorldModel: collector thread still blocked after 2s — continuing shutdown")
            else:
                logger.info("WorldModel: stopped")

    # ── Collector registration ───────────────────────────────────────

    def register_collector(self, collector: BaseCollector) -> None:
        """Register an additional collector (must be called before start)."""
        self._collectors.append(collector)
        logger.info(
            "WorldModel: registered collector %s (interval=%.1fs)",
            type(collector).__name__, collector.poll_interval,
        )

    # ── Public query API ─────────────────────────────────────────────

    def get_snapshot(self) -> WorldSnapshot:
        """Return an immutable copy of the current world snapshot."""
        with self._lock:
            return self._snapshot

    def get_applications(self) -> list[ApplicationInfo]:
        """Return the list of running GUI applications."""
        return self.get_snapshot().applications

    def get_active_application(self) -> ApplicationInfo | None:
        """Return the active (foreground) application, or None."""
        for app in self.get_snapshot().applications:
            if app.is_active:
                return app
        return None

    def get_browser_info(self) -> BrowserInfo | None:
        return self.get_snapshot().browser

    def get_system_info(self) -> SystemInfo | None:
        return self.get_snapshot().system

    def get_media_info(self) -> MediaInfo | None:
        return self.get_snapshot().media

    def get_clipboard(self) -> str:
        sysinfo = self.get_snapshot().system
        if sysinfo is not None:
            return sysinfo.clipboard_text
        return ""

    def get_current_folder(self) -> str | None:
        finfo = self.get_snapshot().files
        if finfo is not None:
            return finfo.current_folder
        return None

    # ── Background loop ──────────────────────────────────────────────

    def _loop(self) -> None:
        """Background loop: tick each collector on its interval."""
        logger.info(
            "WorldModel: thread '%s' started",
            threading.current_thread().name,
        )
        last_collected: dict[int, float] = {
            id(c): 0.0 for c in self._collectors
        }

        while not self._stop.is_set():
            now = time.monotonic()
            changed = False
            fragments: dict[str, Any] = {}

            for collector in self._collectors:
                if self._stop.is_set():
                    break
                cid = id(collector)
                if now - last_collected[cid] >= collector.poll_interval:
                    try:
                        frag = collector.collect()
                        if frag:
                            fragments.update(frag)
                            changed = True
                    except Exception as exc:
                        logger.warning(
                            "WorldModel: collector %s failed: %s",
                            type(collector).__name__, exc,
                        )
                    last_collected[cid] = now

            if changed:
                self._publish(fragments)

            self._stop.wait(0.5)

        logger.info(
            "WorldModel: thread '%s' stopped",
            threading.current_thread().name,
        )

    def _publish(self, fragments: dict[str, Any]) -> None:
        """Merge collector fragments into the current snapshot."""
        with self._lock:
            old = self._snapshot

            apps = self._build_applications(
                fragments.get("applications"),
            ) if "applications" in fragments else old.applications

            browser = self._build_browser(
                fragments.get("browser"),
            ) if "browser" in fragments else old.browser

            files = self._build_files(
                fragments.get("files"),
            ) if "files" in fragments else old.files

            system = self._build_system(
                fragments.get("system"),
            ) if "system" in fragments else old.system

            media = self._build_media(
                fragments.get("media"),
            ) if "media" in fragments else old.media

            self._snapshot = WorldSnapshot(
                timestamp=time.time(),
                applications=apps,
                browser=browser,
                files=files,
                system=system,
                media=media,
            )

    # ── Fragment → typed model builders ──────────────────────────────

    @staticmethod
    def _build_applications(raw: list[dict]) -> list[ApplicationInfo]:
        return [
            ApplicationInfo(
                pid=a["pid"],
                name=a["name"],
                window_title=a["window_title"],
                is_active=a["is_active"],
                process_path=a.get("process_path", ""),
            )
            for a in raw
        ]

    @staticmethod
    def _build_browser(raw: dict | None) -> BrowserInfo | None:
        if raw is None:
            return None
        return BrowserInfo(
            active_browser=raw.get("active_browser"),
            tabs=[
                BrowserTab(title=t["title"], url=t.get("url", ""))
                for t in raw.get("tabs", [])
            ],
            active_url=raw.get("active_url"),
        )

    @staticmethod
    def _build_files(raw: dict | None) -> FileInfo | None:
        if raw is None:
            return None
        return FileInfo(
            current_folder=raw.get("current_folder"),
            recent_files=raw.get("recent_files", []),
            downloads_in_progress=raw.get("downloads_in_progress", []),
        )

    @staticmethod
    def _build_system(raw: dict | None) -> SystemInfo | None:
        if raw is None:
            return None
        return SystemInfo(
            cpu_percent=raw.get("cpu_percent", 0.0),
            ram_percent=raw.get("ram_percent", 0.0),
            gpu_percent=raw.get("gpu_percent", 0.0),
            battery_percent=raw.get("battery_percent", -1.0),
            battery_charging=raw.get("battery_charging", False),
            network_connected=raw.get("network_connected", False),
            clipboard_text=raw.get("clipboard_text", ""),
        )

    @staticmethod
    def _build_media(raw: dict | None) -> MediaInfo | None:
        if raw is None:
            return None
        return MediaInfo(
            is_playing=raw.get("is_playing", False),
            title=raw.get("title"),
            artist=raw.get("artist"),
            app_name=raw.get("app_name"),
            volume=raw.get("volume", 0.5),
            mic_active=raw.get("mic_active", False),
        )
