"""
system_awareness/collectors/processes.py — full process-list collector.

Collects:
  - Every running process (pid, name, exe, cpu%, memory MB/%, create time)
  - Top CPU consumers (Task Manager style)
  - Top RAM consumers
  - Processes that started today

All I/O runs on a background thread via psutil; ``cpu_percent`` uses
per-process interval sampling (0.0 on first call, real values afterwards).
"""

from __future__ import annotations

import datetime
import logging
import time
from typing import Any

import psutil

from world_model.collectors import BaseCollector, logger


class ProcessesCollector(BaseCollector):
    """Collects the full process list with CPU/RAM stats."""

    def __init__(self, poll_interval: float = 3.0) -> None:
        super().__init__(poll_interval)

    def collect(self) -> dict[str, Any]:
        try:
            return self._collect()
        except Exception as exc:
            logger.warning("ProcessesCollector: %s", exc)
            return {}

    def _collect(self) -> dict[str, Any]:
        today_start = self._today_start_timestamp()
        procs = []

        for proc in psutil.process_iter(["pid", "name", "exe", "cpu_percent",
                                         "memory_info", "memory_percent",
                                         "create_time", "status"]):
            try:
                pinfo = proc.info
                mem_info = pinfo["memory_info"]
                memory_mb = (mem_info.rss / (1024 * 1024)) if mem_info else 0.0
                procs.append({
                    "pid": pinfo["pid"],
                    "name": pinfo["name"] or "",
                    "exe": pinfo["exe"] or "",
                    "cpu_percent": float(pinfo["cpu_percent"] or 0.0),
                    "memory_mb": memory_mb,
                    "memory_percent": float(pinfo["memory_percent"] or 0.0),
                    "create_time": float(pinfo["create_time"] or 0.0),
                    "started_today": bool(pinfo["create_time"] and pinfo["create_time"] >= today_start),
                })
            except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                continue

        # Top consumers (Task Manager style)
        top_cpu = sorted(procs, key=lambda p: p["cpu_percent"], reverse=True)[:10]
        top_ram = sorted(procs, key=lambda p: p["memory_mb"], reverse=True)[:10]
        started_today = [p for p in procs if p["started_today"]]

        return {
            "processes": procs,
            "top_cpu_processes": top_cpu,
            "top_ram_processes": top_ram,
            "processes_started_today": started_today,
        }

    @staticmethod
    def _today_start_timestamp() -> float:
        now = datetime.datetime.now()
        start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        return start.timestamp()
