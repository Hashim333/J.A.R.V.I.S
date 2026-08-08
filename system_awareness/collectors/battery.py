"""
system_awareness/collectors/battery.py — battery state collector.

Collects percent, charging, time remaining (psutil) and, when available,
health percent (design capacity vs current full capacity via WMI).  All I/O
runs on a background thread.
"""

from __future__ import annotations

import logging
import time
from typing import Any

import psutil

from world_model.collectors import BaseCollector, logger


class BatteryCollector(BaseCollector):
    """Collects battery level, charging, time remaining and health."""

    def __init__(self, poll_interval: float = 5.0) -> None:
        super().__init__(poll_interval)
        self._health: float | None = None

    def collect(self) -> dict[str, Any]:
        try:
            return self._collect()
        except Exception as exc:
            logger.warning("BatteryCollector: %s", exc)
            return {}

    def _collect(self) -> dict[str, Any]:
        present = False
        percent = -1.0
        charging = False
        seconds = -1.0

        try:
            batt = psutil.sensors_battery()
            if batt is not None:
                present = True
                percent = float(batt.percent)
                charging = bool(batt.power_plugged)
                if batt.secsleft is not None and batt.secsleft > 0:
                    seconds = float(batt.secsleft)
        except Exception:
            pass

        if self._health is None:
            self._health = self._read_health()

        return {
            "battery": {
                "present": present,
                "percent": percent,
                "charging": charging,
                "time_remaining_seconds": seconds,
                "health_percent": self._health,
            },
        }

    @staticmethod
    def _read_health() -> float | None:
        """Design capacity vs full charge capacity via WMI (best-effort)."""
        try:
            import pythoncom  # type: ignore[import-untyped]
            import wmi  # type: ignore[import-untyped]
            pythoncom.CoInitialize()
            client = wmi.WMI()
            bat = client.Win32_Battery()[0]
            design = getattr(bat, "DesignCapacity", None)
            full = getattr(bat, "FullChargeCapacity", None)
            if design and full:
                return min(100.0, round(float(full) / float(design) * 100.0, 1))
        except Exception:
            pass
        return None
