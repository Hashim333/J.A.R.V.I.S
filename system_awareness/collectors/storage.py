"""
system_awareness/collectors/storage.py — storage and recycle-bin collectors.

StorageCollector: per-drive total/used/free (GB) + used % via psutil.
RecycleBinCollector: item count + size (MB) via the Shell API (SHQueryRecycleBin).
"""

from __future__ import annotations

import ctypes
import logging
import time
from typing import Any

import psutil

from world_model.collectors import BaseCollector, logger


class StorageCollector(BaseCollector):
    """Collects per-drive disk usage."""

    def __init__(self, poll_interval: float = 15.0) -> None:
        super().__init__(poll_interval)

    def collect(self) -> dict[str, Any]:
        try:
            return self._collect()
        except Exception as exc:
            logger.warning("StorageCollector: %s", exc)
            return {}

    def _collect(self) -> dict[str, Any]:
        drives = []
        for part in psutil.disk_partitions(all=False):
            if part.fstype in ("", "cdrom", "vfat"):
                continue
            try:
                usage = psutil.disk_usage(part.mountpoint)
            except Exception:
                continue
            drives.append({
                "drive": part.mountpoint.rstrip("\\").rstrip(":/").rstrip("\\"),
                "total_gb": round(usage.total / (1024 ** 3), 1),
                "used_gb": round(usage.used / (1024 ** 3), 1),
                "free_gb": round(usage.free / (1024 ** 3), 1),
                "percent": float(usage.percent),
            })
        return {"storage": drives}


class RecycleBinCollector(BaseCollector):
    """Collects the recycle bin's item count and size."""

    def __init__(self, poll_interval: float = 30.0) -> None:
        super().__init__(poll_interval)

    def collect(self) -> dict[str, Any]:
        try:
            return self._collect()
        except Exception as exc:
            logger.warning("RecycleBinCollector: %s", exc)
            return {}

    def _collect(self) -> dict[str, Any]:
        class _SHQUERYRBINFO(ctypes.Structure):
            _fields_ = [
                ("cbSize", ctypes.c_ulong),
                ("i64Size", ctypes.c_longlong),
                ("i64NumItems", ctypes.c_longlong),
            ]

        info = _SHQUERYRBINFO()
        info.cbSize = ctypes.sizeof(_SHQUERYRBINFO)
        result = ctypes.windll.shell32.SHQueryRecycleBinW(None, ctypes.byref(info))
        if result != 0:
            return {"recycle_bin": None}
        return {
            "recycle_bin": {
                "item_count": int(info.i64NumItems),
                "size_mb": round(info.i64Size / (1024 * 1024), 1),
            },
        }
