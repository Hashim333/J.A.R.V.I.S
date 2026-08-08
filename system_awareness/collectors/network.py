"""
system_awareness/collectors/network.py — network state collector.

Collects:
  - Connectivity (any up interface with an IPv4 address)
  - WiFi SSID + signal % (netsh wlan → psutil fallback)
  - Real-time download/upload throughput (bytes/sec) via net_io_counters deltas
  - IPv4 addresses of active interfaces

Stateful: throughput is computed from the previous sample, so the first
``collect()`` returns 0.0 until a second sample is available.
"""

from __future__ import annotations

import logging
import re
import subprocess
import time
from typing import Any

import psutil

from world_model.collectors import BaseCollector, logger


class NetworkCollector(BaseCollector):
    """Collects connectivity, WiFi, throughput and addresses."""

    def __init__(self, poll_interval: float = 2.0) -> None:
        super().__init__(poll_interval)
        self._last_time: float | None = None
        self._last_counters: tuple[int, int] | None = None

    def collect(self) -> dict[str, Any]:
        try:
            return self._collect()
        except Exception as exc:
            logger.warning("NetworkCollector: %s", exc)
            return {}

    def _collect(self) -> dict[str, Any]:
        counters = psutil.net_io_counters()
        download_bps = 0.0
        upload_bps = 0.0
        now = time.monotonic()

        if (
            self._last_time is not None
            and self._last_counters is not None
            and now > self._last_time
        ):
            elapsed = now - self._last_time
            download_bps = max(0.0, (counters.bytes_recv - self._last_counters[0]) / elapsed)
            upload_bps = max(0.0, (counters.bytes_sent - self._last_counters[1]) / elapsed)

        self._last_time = now
        self._last_counters = (counters.bytes_recv, counters.bytes_sent)

        connected, ipv4 = self._connectivity()
        ssid, signal = self._wifi(connected)

        return {
            "network": {
                "connected": connected,
                "wifi_ssid": ssid,
                "wifi_signal_percent": signal,
                "download_bytes_per_sec": download_bps,
                "upload_bytes_per_sec": upload_bps,
                "ipv4": ipv4,
            },
        }

    @staticmethod
    def _connectivity() -> tuple[bool, list[str]]:
        try:
            addrs = psutil.net_if_addrs()
            stats = psutil.net_if_stats()
            ipv4: list[str] = []
            for iface, s in stats.items():
                if not s.isup or iface not in addrs:
                    continue
                for addr in addrs[iface]:
                    if addr.family == 2 and addr.address:  # AF_INET
                        ipv4.append(addr.address)
            return bool(ipv4), ipv4
        except Exception:
            return False, []

    @staticmethod
    def _wifi(connected: bool) -> tuple[str | None, float | None]:
        """Read WiFi SSID + signal via ``netsh wlan show interfaces``."""
        if not connected:
            return None, None
        try:
            output = subprocess.run(
                ["netsh", "wlan", "show", "interfaces"],
                capture_output=True, text=True, timeout=5.0,
                creationflags=subprocess.CREATE_NO_WINDOW,
            ).stdout
        except Exception:
            return None, None

        ssid = None
        signal = None
        in_connected_state = False
        for line in output.splitlines():
            line = line.strip()
            if "State" in line and "connected" in line.casefold():
                in_connected_state = True
            if "SSID" in line and ":" in line and "BSSID" not in line:
                val = line.split(":", 1)[1].strip()
                if val:
                    ssid = val
            if "Signal" in line and ":" in line:
                m = re.search(r"(\d{1,3})%", line)
                if m:
                    signal = float(m.group(1))
        return (ssid if in_connected_state else None), signal
