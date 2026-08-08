"""
system_awareness/collectors/software.py — software-state collectors.

Collects:
  - Running Windows services (via WMI or ``sc query`` fallback)
  - Recent notifications (best-effort: Action Center XML cache)
  - Media sessions (SMTC via winrt when available)

Each collector degrades to an empty list when its data source is missing.
"""

from __future__ import annotations

import logging
import os
import re
import subprocess
import time
from typing import Any

from world_model.collectors import BaseCollector, logger

_SERVICE_STATES = ("RUNNING", "STOPPED", "PAUSED", "START_PENDING",
                   "STOP_PENDING", "CONTINUE_PENDING", "PAUSE_PENDING")


class ServiceCollector(BaseCollector):
    """Collects running services via ``sc query`` (no WMI dependency)."""

    def __init__(self, poll_interval: float = 30.0) -> None:
        super().__init__(poll_interval)

    def collect(self) -> dict[str, Any]:
        try:
            return self._collect()
        except Exception as exc:
            logger.warning("ServiceCollector: %s", exc)
            return {}

    def _collect(self) -> dict[str, Any]:
        try:
            output = subprocess.run(
                ["sc", "query", "state=", "all"],
                capture_output=True, text=True, timeout=10.0,
                creationflags=subprocess.CREATE_NO_WINDOW,
            ).stdout
        except Exception:
            return {"services": []}

        services = []
        current: dict[str, str] = {}
        for line in output.splitlines():
            line = line.strip()
            if not line:
                continue
            m = re.match(r"SERVICE_NAME:\s+(\S+)", line)
            if m:
                current = {"name": m.group(1), "display_name": "", "status": ""}
                continue
            m = re.match(r"DISPLAY_NAME:\s+(.+)", line)
            if m:
                current["display_name"] = m.group(1).strip()
                continue
            m = re.match(r"STATE\s*:\s+\d+\s+(\S+)", line)
            if m:
                current["status"] = m.group(1)
                if current["name"]:
                    services.append(dict(current))
                    current = {}
        return {"services": services}


class NotificationCollector(BaseCollector):
    """Best-effort collector for recent toast notifications.

    Windows stores recent toast history in an opaque XML cache under
    ``%LOCALAPPDATA%\\Microsoft\\Windows\\Notifications``.  This collector
    parses that cache when present; it returns an empty list otherwise.
    """

    def __init__(self, poll_interval: float = 15.0) -> None:
        super().__init__(poll_interval)
        self._cache_dir = os.path.join(
            os.environ.get("LOCALAPPDATA", ""),
            "Microsoft", "Windows", "Notifications",
        )

    def collect(self) -> dict[str, Any]:
        try:
            return self._collect()
        except Exception as exc:
            logger.warning("NotificationCollector: %s", exc)
            return {}

    def _collect(self) -> dict[str, Any]:
        if not os.path.isdir(self._cache_dir):
            return {"notifications": []}
        notifications = []
        try:
            for fname in os.listdir(self._cache_dir):
                if not fname.endswith((".db", ".xml", ".json")):
                    continue
                path = os.path.join(self._cache_dir, fname)
                if not os.path.isfile(path):
                    continue
                try:
                    with open(path, "r", encoding="utf-8", errors="replace") as fh:
                        data = fh.read(500_000)
                except Exception:
                    continue
                for m in re.finditer(r"<text[^>]*>([^<]{1,200})</text>", data):
                    body = m.group(1).strip()
                    if body:
                        notifications.append({
                            "app_name": fname,
                            "title": "",
                            "body": body,
                            "time": time.time(),
                        })
                if len(notifications) >= 30:
                    break
        except Exception:
            pass
        return {"notifications": notifications[:30]}


class MediaSessionsCollector(BaseCollector):
    """Collects all active media sessions via SMTC (winrt).

    Degrades to an empty list when winrt is unavailable.
    """

    def __init__(self, poll_interval: float = 5.0) -> None:
        super().__init__(poll_interval)
        self._had_smtc_fail = False

    def collect(self) -> dict[str, Any]:
        try:
            return self._collect()
        except Exception as exc:
            logger.warning("MediaSessionsCollector: %s", exc)
            return {}

    def _collect(self) -> dict[str, Any]:
        if self._had_smtc_fail:
            return {"media_sessions": []}
        try:
            import asyncio
            import winrt.windows.media.control as wmc  # type: ignore[import-untyped]

            async def _get():
                mgr = await wmc.GlobalSystemMediaTransportControlsSessionManager.request_async()
                sessions = mgr.get_sessions()
                out = []
                for session in sessions:
                    try:
                        info = await session.try_get_media_properties_async()
                        playback = session.get_playback_info()
                        app = session.source_app_user_model_id or ""
                        app_name = app.split("!")[0].split("_")[0] if app else ""
                        out.append({
                            "app_name": app_name,
                            "title": info.title or "" if info else "",
                            "artist": info.artist or "" if info else "",
                            "is_playing": bool(playback and playback.playback_status == 4),
                        })
                    except Exception:
                        continue
                return out

            return {"media_sessions": asyncio.run(_get())}
        except Exception:
            self._had_smtc_fail = True
            logger.info("MediaSessionsCollector: SMTC unavailable")
            return {"media_sessions": []}
