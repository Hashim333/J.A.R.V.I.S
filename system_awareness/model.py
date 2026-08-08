"""
system_awareness/model.py — immutable data model for the System Awareness Service.

Defines frozen dataclasses for every domain the service tracks and the
comprehensive ``SystemAwarenessSnapshot`` that aggregates them.  Consumers
always receive immutable copies — nothing in the service's internal state
can be mutated from outside.

The awareness service deliberately reuses the existing ``world_model`` for
domains it already covers well (applications, browser tabs, files/downloads,
core system resources, media playback).  This model covers the *additional*
domains the awareness service is responsible for: full process detail,
windows, network quality, battery health, storage, recycle bin, USB/printers/
camera/bluetooth devices, display config, running services, notifications and
media sessions.
"""

from __future__ import annotations

import dataclasses
import time
from typing import Optional


# ── Process / Task Manager domain ─────────────────────────────────────


@dataclasses.dataclass(frozen=True)
class ProcessInfo:
    pid: int
    name: str
    cpu_percent: float
    memory_mb: float
    memory_percent: float
    create_time: float
    started_today: bool
    exe: str = ""


# ── Window domain ─────────────────────────────────────────────────────


@dataclasses.dataclass(frozen=True)
class WindowInfo:
    hwnd: int
    pid: int
    title: str
    is_active: bool
    is_visible: bool


# ── Network domain ────────────────────────────────────────────────────


@dataclasses.dataclass(frozen=True)
class NetworkInfo:
    connected: bool
    wifi_ssid: str | None
    wifi_signal_percent: float | None
    download_bytes_per_sec: float
    upload_bytes_per_sec: float
    ipv4: list[str]


# ── Battery domain ────────────────────────────────────────────────────


@dataclasses.dataclass(frozen=True)
class BatteryInfo:
    percent: float
    charging: bool
    time_remaining_seconds: float
    health_percent: float | None
    present: bool


# ── Storage domain ────────────────────────────────────────────────────


@dataclasses.dataclass(frozen=True)
class StorageInfo:
    drive: str
    total_gb: float
    used_gb: float
    free_gb: float
    percent: float


@dataclasses.dataclass(frozen=True)
class RecycleBinInfo:
    item_count: int
    size_mb: float


# ── Devices domain ────────────────────────────────────────────────────


@dataclasses.dataclass(frozen=True)
class UsbDeviceInfo:
    name: str
    status: str


@dataclasses.dataclass(frozen=True)
class PrinterInfo:
    name: str
    is_default: bool
    is_online: bool
    status: str


@dataclasses.dataclass(frozen=True)
class CameraInfo:
    present: bool
    in_use: bool
    devices: list[str]


@dataclasses.dataclass(frozen=True)
class BluetoothInfo:
    enabled: bool
    devices: list[str]


@dataclasses.dataclass(frozen=True)
class DisplayInfo:
    name: str
    width: int
    height: int
    refresh_hz: int
    is_primary: bool


# ── Software domain ───────────────────────────────────────────────────


@dataclasses.dataclass(frozen=True)
class ServiceInfo:
    name: str
    display_name: str
    status: str


@dataclasses.dataclass(frozen=True)
class NotificationInfo:
    app_name: str
    title: str
    body: str
    time: float


@dataclasses.dataclass(frozen=True)
class MediaSessionInfo:
    app_name: str
    title: str
    artist: str
    is_playing: bool


# ── Top-level snapshot ────────────────────────────────────────────────


@dataclasses.dataclass(frozen=True)
class SystemAwarenessSnapshot:
    """Immutable snapshot of everything the System Awareness Service tracks.

    Every domain degrades gracefully to ``None``/``[]`` rather than erroring:
    a collector that fails (WMI missing, CDP disabled, etc.) results in an
    empty field instead of a crash.
    """

    timestamp: float

    # Processes / task manager
    processes: list[ProcessInfo] = dataclasses.field(default_factory=list)
    top_cpu_processes: list[ProcessInfo] = dataclasses.field(default_factory=list)
    top_ram_processes: list[ProcessInfo] = dataclasses.field(default_factory=list)
    processes_started_today: list[ProcessInfo] = dataclasses.field(default_factory=list)

    # Windows
    windows: list[WindowInfo] = dataclasses.field(default_factory=list)
    focused_window: str | None = None

    # Network
    network: NetworkInfo | None = None

    # Battery
    battery: BatteryInfo | None = None

    # Storage
    storage: list[StorageInfo] = dataclasses.field(default_factory=list)
    recycle_bin: RecycleBinInfo | None = None

    # Devices
    usb_devices: list[UsbDeviceInfo] = dataclasses.field(default_factory=list)
    printers: list[PrinterInfo] = dataclasses.field(default_factory=list)
    camera: CameraInfo | None = None
    bluetooth: BluetoothInfo | None = None
    displays: list[DisplayInfo] = dataclasses.field(default_factory=list)

    # Software
    services: list[ServiceInfo] = dataclasses.field(default_factory=list)
    notifications: list[NotificationInfo] = dataclasses.field(default_factory=list)
    media_sessions: list[MediaSessionInfo] = dataclasses.field(default_factory=list)
    media: object | None = None  # world_model MediaInfo (title/artist/volume/mic)

    # System resources (reused from world_model SystemInfo)
    system: object | None = None

    # ── Convenience queries used by the brain / answers ────────────────

    def browser_tab_count(self, browser_name: str) -> int:
        """Estimate open tabs for a browser from visible window titles.

        Browsers show one window per open browser window; without CDP this
        is the best available live count.  Case-insensitive.
        """
        key = browser_name.strip().casefold()
        stems = {
            "chrome": ("chrome", "google chrome"),
            "msedge": ("edge", "microsoft edge"),
            "edge": ("edge", "microsoft edge"),
            "firefox": ("firefox", "mozilla firefox"),
            "brave": ("brave",),
            "opera": ("opera",),
            "vivaldi": ("vivaldi",),
        }.get(key, (key,))
        count = 0
        for w in self.windows:
            title = w.title.casefold()
            if any(stem in title for stem in stems):
                count += 1
        return count

    def top_ram_process(self) -> ProcessInfo | None:
        return self.top_ram_processes[0] if self.top_ram_processes else None

    def top_cpu_process(self) -> ProcessInfo | None:
        return self.top_cpu_processes[0] if self.top_cpu_processes else None

    def process_named(self, name: str) -> ProcessInfo | None:
        """Return the process matching an exe name (case-insensitive)."""
        key = name.strip().casefold()
        for p in self.processes:
            if p.name.casefold() == key or p.exe.casefold() == key:
                return p
        return None

    def storage_for_drive(self, drive: str) -> StorageInfo | None:
        key = drive.strip().rstrip("\\:/").casefold()
        for s in self.storage:
            if s.drive.casefold() == key:
                return s
        return None

    @staticmethod
    def empty() -> "SystemAwarenessSnapshot":
        return SystemAwarenessSnapshot(timestamp=time.time())
