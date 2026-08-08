"""
skills/registry.py

Persistent Skill Registry.

Every request for a capability that is not yet implemented is stored here
with its skill name, description, date requested, priority, category,
current status, dependencies and notes.  The registry survives restarts.

Persistence format (JSON):

    {
      "version": 1,
      "entries": {
        "email.send": {
          "skill": "email.send",
          "description": "Send and read email",
          "date_requested": "2026-08-03T10:30:00",
          "priority": "high",
          "category": "communication",
          "status": "requested",
          "dependencies": [],
          "notes": "",
          "request_count": 3,
          "last_requested": "2026-08-03T11:15:00",
          "closest_capability": "open your email in the browser, or search",
          "last_request": "send an email to john about the project"
        }
      }
    }

The store is thread-safe and never raises on a corrupt or missing file.
The registry path can be overridden with the ``JARVIS_SKILLS_REGISTRY``
environment variable (used by the test suite).
"""

from __future__ import annotations

import json
import logging
import os
import threading
from datetime import datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

DEFAULT_PRIORITY = "medium"
STATUS_REQUESTED = "requested"
STATUS_IMPLEMENTED = "implemented"
_VALID_STATUSES = frozenset({
    STATUS_REQUESTED, "planned", "in_progress", STATUS_IMPLEMENTED,
})


def _default_path() -> Path:
    override = os.environ.get("JARVIS_SKILLS_REGISTRY")
    if override:
        return Path(override)
    return Path(__file__).resolve().parent.parent / "config" / "skills_registry.json"


def _now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


class SkillRegistry:
    """Persistent store of requested-but-unimplemented skills."""

    def __init__(self, path: str | Path | None = None) -> None:
        self._path = Path(path) if path is not None else _default_path()
        self._lock = threading.Lock()
        self._entries: dict[str, dict[str, Any]] = {}
        self._dirty = False
        self._load()

    # ------------------------------------------------------------------
    # Reading
    # ------------------------------------------------------------------

    @property
    def path(self) -> Path:
        return self._path

    def get(self, skill: str) -> dict[str, Any] | None:
        with self._lock:
            entry = self._entries.get(skill)
            return dict(entry) if entry is not None else None

    def all(self) -> list[dict[str, Any]]:
        """Every entry, newest-first, as a defensive copy."""
        with self._lock:
            entries = list(self._entries.values())
        return sorted(entries, key=lambda e: e.get("date_requested", ""), reverse=True)

    def missing(self, *, include_implemented: bool = False) -> list[dict[str, Any]]:
        """Entries that are still open (status != implemented)."""
        return [
            dict(e) for e in self.all()
            if include_implemented or e.get("status") != STATUS_IMPLEMENTED
        ]

    def count(self) -> int:
        with self._lock:
            return len(self._entries)

    # ------------------------------------------------------------------
    # Writing
    # ------------------------------------------------------------------

    def request(
        self,
        skill: str,
        description: str,
        *,
        category: str = "",
        priority: str | None = None,
        dependencies: list[str] | tuple[str, ...] = (),
        notes: str = "",
        closest_capability: str = "",
        last_request: str = "",
        status: str = STATUS_REQUESTED,
    ) -> dict[str, Any]:
        """Record (or update) a requested skill.

        Repeated requests bump ``request_count`` and escalate the priority
        to ``high`` so the most-requested features float to the top.
        Returns the resulting entry.
        """
        if status not in _VALID_STATUSES:
            status = STATUS_REQUESTED
        now = _now_iso()
        with self._lock:
            entry = self._entries.get(skill)
            if entry is None:
                entry = {
                    "skill": skill,
                    "description": description,
                    "date_requested": now,
                    "priority": priority or DEFAULT_PRIORITY,
                    "category": category,
                    "status": status,
                    "dependencies": list(dependencies),
                    "notes": notes,
                    "request_count": 1,
                    "last_requested": now,
                    "closest_capability": closest_capability,
                    "last_request": last_request,
                }
            else:
                count = int(entry.get("request_count", 0)) + 1
                entry["request_count"] = count
                entry["last_requested"] = now
                entry["description"] = description or entry.get("description", "")
                if category:
                    entry["category"] = category
                if notes:
                    entry["notes"] = notes
                if closest_capability:
                    entry["closest_capability"] = closest_capability
                if last_request:
                    entry["last_request"] = last_request
                if status != STATUS_IMPLEMENTED:
                    entry["status"] = status
                if entry.get("priority") != "high" and count >= 2:
                    entry["priority"] = "high"
            self._entries[skill] = entry
            self._dirty = True
        self._save()
        return dict(entry)

    def mark_implemented(self, skill: str) -> dict[str, Any] | None:
        """Flip a skill's status to ``implemented`` (the record stays)."""
        with self._lock:
            entry = self._entries.get(skill)
            if entry is None:
                return None
            entry["status"] = STATUS_IMPLEMENTED
            entry["notes"] = "Implemented."
            self._dirty = True
        self._save()
        return dict(entry)

    def set_status(self, skill: str, status: str) -> dict[str, Any] | None:
        if status not in _VALID_STATUSES:
            raise ValueError(f"invalid skill status: {status!r}")
        with self._lock:
            entry = self._entries.get(skill)
            if entry is None:
                return None
            entry["status"] = status
            self._dirty = True
        self._save()
        return dict(entry)

    def remove(self, skill: str) -> bool:
        with self._lock:
            existed = self._entries.pop(skill, None) is not None
            if existed:
                self._dirty = True
        if existed:
            self._save()
        return existed

    def reset(self) -> None:
        """Clear every entry (used by tests)."""
        with self._lock:
            self._entries.clear()
            self._dirty = True
        self._save()

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def _load(self) -> None:
        try:
            if not self._path.exists():
                return
            data = json.loads(self._path.read_text(encoding="utf-8"))
            entries = data.get("entries", {})
            if not isinstance(entries, dict):
                entries = {}
            for skill, entry in entries.items():
                if isinstance(entry, dict) and isinstance(skill, str):
                    self._entries[skill] = entry
        except Exception as exc:
            logger.warning(
                "SkillRegistry: could not load %s (%s) — starting empty",
                self._path, exc,
            )

    def _save(self) -> None:
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            data = {"version": 1, "entries": self._entries}
            tmp = self._path.with_suffix(self._path.suffix + ".tmp")
            tmp.write_text(
                json.dumps(data, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
            tmp.replace(self._path)
        except Exception as exc:
            logger.warning("SkillRegistry: could not save %s (%s)", self._path, exc)
