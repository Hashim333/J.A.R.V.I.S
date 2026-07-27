from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class BrowserTabInfo:
    id: int
    window_id: int
    title: str
    url: str
    active: bool
    content_classification: str = "unknown"


@dataclass(frozen=True)
class BrowserWindowInfo:
    name: str
    display_name: str
    debug_port: int | None = None
    process_name: str = ""
    tabs: list[BrowserTabInfo] = field(default_factory=list)
    active_tab: BrowserTabInfo | None = None


@dataclass(frozen=True)
class RunningAppInfo:
    process_name: str
    display_name: str
    windows: list[dict[str, Any]] = field(default_factory=list)
    is_focused: bool = False


@dataclass(frozen=True)
class PendingDialogInfo:
    dialog_type: str
    app_name: str
    title: str = ""


@dataclass(frozen=True)
class ContextSnapshot:
    apps: list[RunningAppInfo] = field(default_factory=list)
    browsers: list[BrowserWindowInfo] = field(default_factory=list)
    active_tab: BrowserTabInfo | None = None
    active_browser: BrowserWindowInfo | None = None
    music_playing: bool = False
    video_playing: bool = False
    protected_tabs: list[BrowserTabInfo] = field(default_factory=list)
    work_tabs: list[BrowserTabInfo] = field(default_factory=list)
    dialogs: list[PendingDialogInfo] = field(default_factory=list)
    has_profile_picker: bool = False
    timestamp: float = 0.0
