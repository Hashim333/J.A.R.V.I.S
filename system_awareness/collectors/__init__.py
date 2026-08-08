"""
system_awareness/collectors/__init__.py — domain collectors for the
System Awareness Service.

Collectors reuse the same ``BaseCollector`` contract as the world model:
a ``poll_interval`` and a ``collect()`` that returns a dict fragment.  The
SystemAwarenessService merges fragments into a ``SystemAwarenessSnapshot``.
"""

from __future__ import annotations

from system_awareness.collectors.battery import BatteryCollector
from system_awareness.collectors.devices import (
    BluetoothCollector,
    CameraCollector,
    DisplayCollector,
    PrinterCollector,
    UsbCollector,
)
from system_awareness.collectors.network import NetworkCollector
from system_awareness.collectors.processes import ProcessesCollector
from system_awareness.collectors.software import (
    MediaSessionsCollector,
    NotificationCollector,
    ServiceCollector,
)
from system_awareness.collectors.storage import (
    RecycleBinCollector,
    StorageCollector,
)
from system_awareness.collectors.windows import WindowsCollector
from world_model.collectors import BaseCollector

__all__ = [
    "BaseCollector",
    "ProcessesCollector",
    "WindowsCollector",
    "NetworkCollector",
    "BatteryCollector",
    "StorageCollector",
    "RecycleBinCollector",
    "UsbCollector",
    "PrinterCollector",
    "CameraCollector",
    "BluetoothCollector",
    "DisplayCollector",
    "ServiceCollector",
    "NotificationCollector",
    "MediaSessionsCollector",
]
