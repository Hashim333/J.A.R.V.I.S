"""
system_awareness/system_awareness.py — System Awareness Service.

Continuously maintains live computer state so the brain can answer instantly
without searching: processes, windows, network, battery, storage, devices,
services, notifications and media sessions.

Reuses the existing ``world_model`` for domains it already covers well
(applications, browser tabs, files/downloads, core resources, media
playback), and adds its own collectors for the richer awareness domains.

Thread model
------------
- One background thread (``_loop``) drives all awareness collectors
  sequentially, each on its own ``poll_interval``.
- The current snapshot is protected by a ``threading.Lock`` — reads and
  writes are thread-safe.
- Collectors may use blocking I/O (psutil, WMI, Win32, subprocess); none of
  that touches the UI thread.

Usage
-----
    from system_awareness import SystemAwarenessService

    svc = SystemAwarenessService()
    svc.start()
    snap = svc.current()          # thread-safe immutable snapshot
    print(snap.top_ram_process())
    svc.stop()
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Any

from system_awareness.collectors import (
    BatteryCollector,
    BluetoothCollector,
    CameraCollector,
    DisplayCollector,
    MediaSessionsCollector,
    NetworkCollector,
    NotificationCollector,
    PrinterCollector,
    ProcessesCollector,
    RecycleBinCollector,
    ServiceCollector,
    StorageCollector,
    UsbCollector,
    WindowsCollector,
)
from system_awareness.collectors import BaseCollector
from system_awareness.model import (
    BatteryInfo,
    BluetoothInfo,
    CameraInfo,
    DisplayInfo,
    MediaSessionInfo,
    NetworkInfo,
    NotificationInfo,
    PrinterInfo,
    ProcessInfo,
    RecycleBinInfo,
    ServiceInfo,
    StorageInfo,
    SystemAwarenessSnapshot,
    UsbDeviceInfo,
    WindowInfo,
)

logger = logging.getLogger(__name__)


class SystemAwarenessService:
    """Orchestrates awareness collectors and exposes a thread-safe query API."""

    def __init__(
        self,
        collectors: list[BaseCollector] | None = None,
        world_model: Any = None,
        browser_detector: Any = None,
    ) -> None:
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._snapshot: SystemAwarenessSnapshot = SystemAwarenessSnapshot.empty()
        self._world_model = world_model
        self._browser_detector = browser_detector

        self._collectors: list[BaseCollector] = (
            collectors if collectors is not None else [
                ProcessesCollector(),
                WindowsCollector(),
                NetworkCollector(),
                BatteryCollector(),
                StorageCollector(),
                RecycleBinCollector(),
                UsbCollector(),
                PrinterCollector(),
                CameraCollector(),
                BluetoothCollector(),
                DisplayCollector(),
                ServiceCollector(),
                NotificationCollector(),
                MediaSessionsCollector(),
            ]
        )

    # ── Lifecycle ─────────────────────────────────────────────────────

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            logger.warning("SystemAwarenessService: already running")
            return
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._loop, name="system-awareness", daemon=True,
        )
        self._thread.start()
        logger.info(
            "SystemAwarenessService: started with %d collectors",
            len(self._collectors),
        )

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=2.0)
            if self._thread.is_alive():
                logger.warning("SystemAwarenessService: collector thread still blocked after 2s — continuing shutdown")
            else:
                logger.info("SystemAwarenessService: stopped")

    # ── Public query API ──────────────────────────────────────────────

    def current(self) -> SystemAwarenessSnapshot:
        """Return an immutable copy of the current awareness snapshot."""
        with self._lock:
            return self._snapshot

    def snapshot(self) -> SystemAwarenessSnapshot:
        return self.current()

    # ── Background loop ───────────────────────────────────────────────

    def _loop(self) -> None:
        logger.info(
            "SystemAwarenessService: thread '%s' started",
            threading.current_thread().name,
        )
        last_collected: dict[int, float] = {
            id(c): 0.0 for c in self._collectors
        }

        while not self._stop.is_set():
            now = time.monotonic()

            for collector in self._collectors:
                if self._stop.is_set():
                    break
                cid = id(collector)
                if now - last_collected[cid] >= collector.poll_interval:
                    try:
                        frag = collector.collect()
                        if frag:
                            self._publish(frag)
                    except Exception as exc:
                        logger.warning(
                            "SystemAwarenessService: collector %s failed: %s",
                            type(collector).__name__, exc,
                        )
                    last_collected[cid] = now

            self._stop.wait(0.5)

        logger.info(
            "SystemAwarenessService: thread '%s' stopped",
            threading.current_thread().name,
        )

    # ── Snapshot builder ──────────────────────────────────────────────

    def _publish(self, fragments: dict[str, Any]) -> None:
        with self._lock:
            old = self._snapshot
            new = SystemAwarenessSnapshot(
                timestamp=time.time(),
                processes=self._build_processes(
                    fragments.get("processes"), old.processes,
                ),
                top_cpu_processes=self._build_processes(
                    fragments.get("top_cpu_processes"), old.top_cpu_processes,
                ),
                top_ram_processes=self._build_processes(
                    fragments.get("top_ram_processes"), old.top_ram_processes,
                ),
                processes_started_today=self._build_processes(
                    fragments.get("processes_started_today"),
                    old.processes_started_today,
                ),
                windows=self._build_windows(
                    fragments.get("windows"), old.windows,
                ),
                focused_window=fragments.get(
                    "focused_window", old.focused_window,
                ),
                network=self._build_network(fragments.get("network"), old.network),
                battery=self._build_battery(fragments.get("battery"), old.battery),
                storage=self._build_storage(fragments.get("storage"), old.storage),
                recycle_bin=self._build_recycle_bin(
                    fragments.get("recycle_bin"), old.recycle_bin,
                ),
                usb_devices=self._build_usb(
                    fragments.get("usb_devices"), old.usb_devices,
                ),
                printers=self._build_printers(
                    fragments.get("printers"), old.printers,
                ),
                camera=self._build_camera(fragments.get("camera"), old.camera),
                bluetooth=self._build_bluetooth(
                    fragments.get("bluetooth"), old.bluetooth,
                ),
                displays=self._build_displays(
                    fragments.get("displays"), old.displays,
                ),
                services=self._build_services(
                    fragments.get("services"), old.services,
                ),
                notifications=self._build_notifications(
                    fragments.get("notifications"), old.notifications,
                ),
                media_sessions=self._build_media_sessions(
                    fragments.get("media_sessions"), old.media_sessions,
                ),
                media=self._world_media(),
                system=self._world_system(),
            )
            self._snapshot = new

    # ── Fragment → typed model builders ───────────────────────────────

    @staticmethod
    def _build_processes(raw: Any, old: list[ProcessInfo]) -> list[ProcessInfo]:
        if raw is None:
            return old
        return [
            ProcessInfo(
                pid=p["pid"],
                name=p["name"],
                cpu_percent=p["cpu_percent"],
                memory_mb=p["memory_mb"],
                memory_percent=p["memory_percent"],
                create_time=p["create_time"],
                started_today=p["started_today"],
                exe=p.get("exe", ""),
            )
            for p in raw
        ]

    @staticmethod
    def _build_windows(raw: Any, old: list[WindowInfo]) -> list[WindowInfo]:
        if raw is None:
            return old
        return [
            WindowInfo(
                hwnd=w["hwnd"],
                pid=w["pid"],
                title=w["title"],
                is_active=w["is_active"],
                is_visible=w["is_visible"],
            )
            for w in raw
        ]

    @staticmethod
    def _build_network(raw: Any, old: NetworkInfo | None) -> NetworkInfo | None:
        if raw is None:
            return old
        return NetworkInfo(
            connected=raw.get("connected", False),
            wifi_ssid=raw.get("wifi_ssid"),
            wifi_signal_percent=raw.get("wifi_signal_percent"),
            download_bytes_per_sec=raw.get("download_bytes_per_sec", 0.0),
            upload_bytes_per_sec=raw.get("upload_bytes_per_sec", 0.0),
            ipv4=raw.get("ipv4", []),
        )

    @staticmethod
    def _build_battery(raw: Any, old: BatteryInfo | None) -> BatteryInfo | None:
        if raw is None:
            return old
        return BatteryInfo(
            percent=raw.get("percent", -1.0),
            charging=raw.get("charging", False),
            time_remaining_seconds=raw.get("time_remaining_seconds", -1.0),
            health_percent=raw.get("health_percent"),
            present=raw.get("present", False),
        )

    @staticmethod
    def _build_storage(raw: Any, old: list[StorageInfo]) -> list[StorageInfo]:
        if raw is None:
            return old
        return [
            StorageInfo(
                drive=s["drive"],
                total_gb=s["total_gb"],
                used_gb=s["used_gb"],
                free_gb=s["free_gb"],
                percent=s["percent"],
            )
            for s in raw
        ]

    @staticmethod
    def _build_recycle_bin(raw: Any, old: RecycleBinInfo | None) -> RecycleBinInfo | None:
        if raw is None:
            return old
        return RecycleBinInfo(
            item_count=raw.get("item_count", 0),
            size_mb=raw.get("size_mb", 0.0),
        )

    @staticmethod
    def _build_usb(raw: Any, old: list[UsbDeviceInfo]) -> list[UsbDeviceInfo]:
        if raw is None:
            return old
        return [
            UsbDeviceInfo(name=d["name"], status=d.get("status", ""))
            for d in raw
        ]

    @staticmethod
    def _build_printers(raw: Any, old: list[PrinterInfo]) -> list[PrinterInfo]:
        if raw is None:
            return old
        return [
            PrinterInfo(
                name=p["name"],
                is_default=p.get("is_default", False),
                is_online=p.get("is_online", True),
                status=str(p.get("status", "")),
            )
            for p in raw
        ]

    @staticmethod
    def _build_camera(raw: Any, old: CameraInfo | None) -> CameraInfo | None:
        if raw is None:
            return old
        return CameraInfo(
            present=raw.get("present", False),
            in_use=raw.get("in_use", False),
            devices=raw.get("devices", []),
        )

    @staticmethod
    def _build_bluetooth(raw: Any, old: BluetoothInfo | None) -> BluetoothInfo | None:
        if raw is None:
            return old
        return BluetoothInfo(
            enabled=raw.get("enabled", False),
            devices=raw.get("devices", []),
        )

    @staticmethod
    def _build_displays(raw: Any, old: list[DisplayInfo]) -> list[DisplayInfo]:
        if raw is None:
            return old
        return [
            DisplayInfo(
                name=d["name"],
                width=d["width"],
                height=d["height"],
                refresh_hz=d.get("refresh_hz", 0),
                is_primary=d.get("is_primary", False),
            )
            for d in raw
        ]

    @staticmethod
    def _build_services(raw: Any, old: list[ServiceInfo]) -> list[ServiceInfo]:
        if raw is None:
            return old
        return [
            ServiceInfo(
                name=s["name"],
                display_name=s.get("display_name", s["name"]),
                status=s.get("status", ""),
            )
            for s in raw
        ]

    @staticmethod
    def _build_notifications(raw: Any, old: list[NotificationInfo]) -> list[NotificationInfo]:
        if raw is None:
            return old
        return [
            NotificationInfo(
                app_name=n.get("app_name", ""),
                title=n.get("title", ""),
                body=n.get("body", ""),
                time=n.get("time", 0.0),
            )
            for n in raw
        ]

    @staticmethod
    def _build_media_sessions(raw: Any, old: list[MediaSessionInfo]) -> list[MediaSessionInfo]:
        if raw is None:
            return old
        return [
            MediaSessionInfo(
                app_name=s.get("app_name", ""),
                title=s.get("title", ""),
                artist=s.get("artist", ""),
                is_playing=s.get("is_playing", False),
            )
            for s in raw
        ]

    def _world_media(self) -> Any:
        if self._world_model is None:
            return None
        try:
            return self._world_model.get_snapshot().media
        except Exception:
            return None

    def _world_system(self) -> Any:
        if self._world_model is None:
            return None
        try:
            return self._world_model.get_snapshot().system
        except Exception:
            return None
