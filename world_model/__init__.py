"""
world_model — Structured representation of the computer's state.

Public API
----------
    from world_model import WorldModel, WorldSnapshot

    wm = WorldModel()
    wm.start()
    snapshot = wm.get_snapshot()
    wm.stop()

Classes
-------
- ``WorldModel`` — orchestrator with background polling and query API
- ``WorldSnapshot`` — immutable snapshot of everything the model tracks
- ``ApplicationInfo``, ``BrowserInfo``, ``FileInfo``, ``SystemInfo``,
  ``MediaInfo`` — domain-specific snapshot fragments
"""

from world_model.model import (
    ApplicationInfo,
    BrowserInfo,
    BrowserTab,
    FileInfo,
    MediaInfo,
    SystemInfo,
    WorldSnapshot,
)
from world_model.world_model import WorldModel

__all__ = [
    "WorldModel",
    "WorldSnapshot",
    "ApplicationInfo",
    "BrowserInfo",
    "BrowserTab",
    "FileInfo",
    "MediaInfo",
    "SystemInfo",
]
