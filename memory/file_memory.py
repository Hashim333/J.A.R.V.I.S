"""
memory/file_memory.py

Tracks frequently accessed files so JARVIS can offer better suggestions
when a user asks for a file by name.
"""

from __future__ import annotations

import json
import logging
import os
import time
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


class FileMemory:
    """Persistent tracker of file access frequency and recency.

    Data is stored as a JSON file in the user's app data directory.
    """

    _instance: FileMemory | None = None

    def __init__(self, storage_path: str | None = None) -> None:
        if storage_path is None:
            storage_path = self._default_storage_path()
        self._storage_path: str = storage_path
        self._data: dict[str, dict[str, Any]] = {}
        self._loaded: bool = False

    @staticmethod
    def _default_storage_path() -> str:
        appdata = os.environ.get("LOCALAPPDATA", os.path.expanduser("~"))
        path = os.path.join(appdata, "JARVIS", "file_memory.json")
        os.makedirs(os.path.dirname(path), exist_ok=True)
        return path

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def _load(self) -> None:
        if self._loaded:
            return
        try:
            with open(self._storage_path, encoding="utf-8") as f:
                self._data = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            self._data = {}
        self._loaded = True

    def _save(self) -> None:
        try:
            with open(self._storage_path, "w", encoding="utf-8") as f:
                json.dump(self._data, f, indent=2)
        except Exception as exc:
            logger.warning("Could not save file memory: %s", exc)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def record_access(self, file_path: str) -> None:
        """Record that a file was accessed (opened, found, etc.)."""
        self._load()
        path = Path(file_path).resolve()
        key = str(path).casefold()
        now = time.time()
        entry = self._data.get(key, {})
        entry["path"] = str(path)
        entry["last_accessed"] = now
        entry["access_count"] = entry.get("access_count", 0) + 1
        entry["name"] = path.name
        self._data[key] = entry
        self._save()

    def get_frequently_used(self, limit: int = 10) -> list[dict[str, Any]]:
        """Return the most frequently accessed files.

        Items are sorted by (access_count DESC, last_accessed DESC).
        """
        self._load()
        sorted_items = sorted(
            self._data.values(),
            key=lambda x: (x.get("access_count", 0), x.get("last_accessed", 0)),
            reverse=True,
        )
        return [
            {
                "path": item["path"],
                "name": item.get("name", Path(item["path"]).name),
                "access_count": item.get("access_count", 0),
                "last_accessed": item.get("last_accessed", 0),
            }
            for item in sorted_items[:limit]
        ]

    def get_recent_files(self, days: int = 7, limit: int = 10) -> list[dict[str, Any]]:
        """Return files accessed within *days*."""
        self._load()
        cutoff = time.time() - days * 86400
        recent = [
            v for v in self._data.values()
            if v.get("last_accessed", 0) >= cutoff
        ]
        recent.sort(key=lambda x: x.get("last_accessed", 0), reverse=True)
        return [
            {
                "path": item["path"],
                "name": item.get("name", Path(item["path"]).name),
                "last_accessed": item.get("last_accessed", 0),
            }
            for item in recent[:limit]
        ]

    def search_with_memory(
        self, query: str, max_results: int = 10,
    ) -> list[dict[str, Any]]:
        """Search remembered files by name substring, sorted by recency."""
        self._load()
        query_lower = query.casefold()
        matches: list[dict[str, Any]] = []
        for entry in self._data.values():
            name = entry.get("name", Path(entry["path"]).name)
            if query_lower in name.casefold():
                matches.append({
                    "path": entry["path"],
                    "name": name,
                    "access_count": entry.get("access_count", 0),
                    "last_accessed": entry.get("last_accessed", 0),
                })
        matches.sort(
            key=lambda x: (x["access_count"], x["last_accessed"]),
            reverse=True,
        )
        return matches[:max_results]

    def clear(self) -> None:
        """Wipe all remembered file data."""
        self._data = {}
        self._save()
        logger.info("File memory cleared.")
