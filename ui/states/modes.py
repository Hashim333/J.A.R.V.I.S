"""
ui/states/modes.py

Window mode definitions for the JARVIS UI.
"""

from __future__ import annotations

from enum import Enum


class WindowMode(Enum):
    FULLSCREEN = "fullscreen"
    FLOATING_ORB = "floating_orb"
    EDGE_DOCK = "edge_dock"
    SYSTEM_TRAY = "system_tray"


class CoreState(Enum):
    IDLE = "idle"
    LISTENING = "listening"
    THINKING = "thinking"
    SPEAKING = "speaking"
    ERROR = "error"
    OFFLINE = "offline"
