"""
system_awareness — System Awareness Service.

Continuously maintains live computer state (processes, windows, network,
battery, storage, devices, services, notifications, media sessions) so the
brain can answer questions instantly without searching.  Reuses the
``world_model`` for the shared core domains.

Public API
----------
    from system_awareness import SystemAwarenessService

    svc = SystemAwarenessService(world_model=world_model)
    svc.start()
    snap = svc.current()
    svc.stop()

Instant answers::

    from system_awareness import answer
    reply = answer(snap, "which app uses most RAM?")

Classes
-------
- ``SystemAwarenessService`` — orchestrator with background polling
- ``SystemAwarenessSnapshot`` — immutable snapshot of everything tracked
- Domain dataclasses: ProcessInfo, WindowInfo, NetworkInfo, BatteryInfo,
  StorageInfo, RecycleBinInfo, UsbDeviceInfo, PrinterInfo, CameraInfo,
  BluetoothInfo, DisplayInfo, ServiceInfo, NotificationInfo, MediaSessionInfo
"""

from system_awareness.answers import answer, describe
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
from system_awareness.system_awareness import SystemAwarenessService

__all__ = [
    "SystemAwarenessService",
    "SystemAwarenessSnapshot",
    "answer",
    "describe",
    "ProcessInfo",
    "WindowInfo",
    "NetworkInfo",
    "BatteryInfo",
    "StorageInfo",
    "RecycleBinInfo",
    "UsbDeviceInfo",
    "PrinterInfo",
    "CameraInfo",
    "BluetoothInfo",
    "DisplayInfo",
    "ServiceInfo",
    "NotificationInfo",
    "MediaSessionInfo",
]
