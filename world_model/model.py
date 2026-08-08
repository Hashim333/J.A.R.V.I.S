"""
world_model/model.py — Immutable data model for the World Model.

All snapshots are frozen dataclasses — consumers receive read-only copies.
"""

from __future__ import annotations

import dataclasses
import time
from typing import Optional


# ── Application domain ───────────────────────────────────────────────


@dataclasses.dataclass(frozen=True)
class ApplicationInfo:
    pid: int
    name: str
    window_title: str
    is_active: bool
    process_path: str = ""


# ── Browser domain ───────────────────────────────────────────────────


@dataclasses.dataclass(frozen=True)
class BrowserTab:
    title: str
    url: str


@dataclasses.dataclass(frozen=True)
class BrowserInfo:
    active_browser: str | None
    tabs: list[BrowserTab]
    active_url: str | None


# ── File domain ──────────────────────────────────────────────────────


@dataclasses.dataclass(frozen=True)
class FileInfo:
    current_folder: str | None
    recent_files: list[str]
    downloads_in_progress: list[str]


# ── System domain ────────────────────────────────────────────────────


@dataclasses.dataclass(frozen=True)
class SystemInfo:
    cpu_percent: float
    ram_percent: float
    gpu_percent: float
    battery_percent: float
    battery_charging: bool
    network_connected: bool
    clipboard_text: str


# ── Media domain ─────────────────────────────────────────────────────


@dataclasses.dataclass(frozen=True)
class MediaInfo:
    is_playing: bool
    title: str | None
    artist: str | None
    app_name: str | None
    volume: float
    mic_active: bool


# ── Top-level snapshot ───────────────────────────────────────────────


@dataclasses.dataclass(frozen=True)
class WorldSnapshot:
    """Immutable snapshot of the computer's current state.

    Every consumer receives a frozen copy — the World Model's internal
    state can never be mutated from outside.
    """
    timestamp: float
    applications: list[ApplicationInfo]
    browser: Optional[BrowserInfo]
    files: Optional[FileInfo]
    system: Optional[SystemInfo]
    media: Optional[MediaInfo]

    @staticmethod
    def empty() -> WorldSnapshot:
        return WorldSnapshot(
            timestamp=time.time(),
            applications=[],
            browser=None,
            files=None,
            system=None,
            media=None,
        )
