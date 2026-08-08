"""
working_memory/working_memory.py — Thread-safe short-term memory service.

Maintains a structured, time-bounded record of the current conversation,
active task, and computer state.  Entries auto-expire unless marked
persistent.  Singleton types (current-Task, current-file, ...) replace
rather than accumulate.  List types (commands, actions, goals) enforce
per-type maximum counts.

Thread model
------------
- All public methods are thread-safe via ``threading.Lock``.
- A background daemon thread (``_eviction_loop``) runs eviction every 60 s.
- Consumers (Brain, Planner) call only read methods — direct mutation is
  reserved for the conversation handler or system integrator.

Usage
-----
    from working_memory import WorkingMemory

    wm = WorkingMemory()
    wm.start()

    wm.add_command("find the tests for user auth")
    wm.add_action("found tests/test_auth.py")

    task = wm.get_current_task()
    print(task)

    wm.stop()
"""

from __future__ import annotations

import logging
import threading
import time
import uuid
from typing import Any

from working_memory.model import (
    LIST_TYPE_MAX,
    SINGLETON_TYPES,
    MemoryEntry,
    MemoryType,
)

logger = logging.getLogger(__name__)

# Default TTL in seconds for list-type entries when no explicit expiry is set.
_DEFAULT_TTL: dict[MemoryType, float | None] = {
    MemoryType.USER_COMMAND: 1800.0,         # 30 min
    MemoryType.ASSISTANT_ACTION: 1800.0,     # 30 min
    MemoryType.PENDING_GOAL: 3600.0,         # 1 h
    MemoryType.PENDING_CONFIRMATION: 1800.0, # 30 min
    MemoryType.CURRENT_TASK: None,           # persistent
    MemoryType.CURRENT_PROJECT: None,
    MemoryType.CURRENT_APPLICATION: None,
    MemoryType.CURRENT_FILE: None,
    MemoryType.CURRENT_BROWSER_TAB: None,
    MemoryType.CURRENT_FOLDER: None,
    MemoryType.CONVERSATION_CONTEXT: None,
}


class WorkingMemory:
    """Thread-safe short-term memory service.

    Public methods are safe to call from any thread.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._stop = threading.Event()

        # Primary store: id → MemoryEntry
        self._entries: dict[str, MemoryEntry] = {}

        # Secondary index: type → ordered list of ids (newest first)
        self._by_type: dict[MemoryType, list[str]] = {
            t: [] for t in MemoryType
        }

        self._eviction_thread: threading.Thread | None = None

    # ── Lifecycle ─────────────────────────────────────────────────────

    def start(self) -> None:
        """Start the background eviction thread."""
        if self._eviction_thread is not None and self._eviction_thread.is_alive():
            logger.warning("WorkingMemory: already running")
            return
        self._stop.clear()
        self._eviction_thread = threading.Thread(
            target=self._eviction_loop,
            name="working-memory",
            daemon=True,
        )
        self._eviction_thread.start()
        logger.info("WorkingMemory: started")

    def stop(self) -> None:
        """Signal the background eviction loop and wait for it."""
        self._stop.set()
        if self._eviction_thread is not None:
            self._eviction_thread.join(timeout=5.0)
            logger.info("WorkingMemory: stopped")

    # ── Add ───────────────────────────────────────────────────────────

    def add(self, type: MemoryType, content: str, *,
            ttl_seconds: float | None | None = None,
            metadata: dict[str, Any] | None = None,
            id: str | None = None,
            ) -> str:
        """Add a new memory entry and return its id.

        Parameters
        ----------
        type:
            The category of memory.
        content:
            Human-readable payload string.
        ttl_seconds:
            Override the default time-to-live.  ``None`` means *use the
            type's default* (which may itself be ``None`` → persistent).
            Pass a negative value to force persistent.
        metadata:
            Optional structured key-value data.
        id:
            Explicit id (auto-generated UUID if omitted).

        Notes
        -----
        - ``SINGLETON_TYPES`` replace any existing entry of the same type.
        - List types are trimmed to their ``LIST_TYPE_MAX`` after insert.
        """
        entry_id = id or uuid.uuid4().hex

        resolved_ttl = (
            _DEFAULT_TTL[type] if ttl_seconds is None
            else ttl_seconds
        )
        expires_at: float | None = None
        if resolved_ttl is not None and resolved_ttl >= 0:
            expires_at = time.time() + resolved_ttl

        entry = MemoryEntry(
            id=entry_id,
            type=type,
            content=content,
            timestamp=time.time(),
            expires_at=expires_at,
            metadata=metadata or {},
        )

        with self._lock:
            if type in SINGLETON_TYPES:
                # Remove any existing entry of this singleton type
                existing_ids = self._by_type[type]
                for eid in existing_ids:
                    self._entries.pop(eid, None)
                existing_ids.clear()

            self._entries[entry.id] = entry
            self._by_type[type].insert(0, entry.id)
            self._trim_list(type)

        return entry.id

    def add_command(self, content: str, **kwargs: Any) -> str:
        """Shorthand for ``add(MemoryType.USER_COMMAND, content, ...)``."""
        return self.add(MemoryType.USER_COMMAND, content, **kwargs)

    def add_action(self, content: str, **kwargs: Any) -> str:
        """Shorthand for ``add(MemoryType.ASSISTANT_ACTION, content, ...)``."""
        return self.add(MemoryType.ASSISTANT_ACTION, content, **kwargs)

    def add_goal(self, content: str, **kwargs: Any) -> str:
        """Shorthand for ``add(MemoryType.PENDING_GOAL, content, ...)``."""
        return self.add(MemoryType.PENDING_GOAL, content, **kwargs)

    def add_confirmation(self, content: str, **kwargs: Any) -> str:
        """Shorthand for ``add(MemoryType.PENDING_CONFIRMATION, content, ...)``."""
        return self.add(MemoryType.PENDING_CONFIRMATION, content, **kwargs)

    # ── Update ───────────────────────────────────────────────────────

    def update(self, id: str, *,
               content: str | None = None,
               metadata: dict[str, Any] | None = None,
               extend_ttl: float | None = None,
               ) -> bool:
        """Update an existing entry's content/metadata/ttl.

        Returns ``True`` if the entry was found and updated, ``False`` if
        the entry does not exist (or has already been evicted).
        """
        with self._lock:
            entry = self._entries.get(id)
            if entry is None:
                return False

            new_content = content if content is not None else entry.content
            new_meta = metadata if metadata is not None else entry.metadata
            new_expires: float | None = entry.expires_at
            if extend_ttl is not None:
                new_expires = time.time() + extend_ttl

            # Replace with a new frozen entry (same id).
            self._entries[id] = MemoryEntry(
                id=entry.id,
                type=entry.type,
                content=new_content,
                timestamp=entry.timestamp,
                expires_at=new_expires,
                metadata=new_meta,
            )
        return True

    # ── Query ─────────────────────────────────────────────────────────

    def query(self,
              type: MemoryType | None = None,
              limit: int = 0,
              include_expired: bool = False,
              ) -> list[MemoryEntry]:
        """Query memory entries, optionally filtered by type.

        Returns entries ordered newest-first.  Expired entries are
        excluded unless ``include_expired=True``.
        """
        with self._lock:
            return self._query_locked(type, limit, include_expired)

    def _query_locked(self,
                      type: MemoryType | None,
                      limit: int,
                      include_expired: bool,
                      ) -> list[MemoryEntry]:
        """Non-locking query helper (caller must hold ``_lock``)."""
        now = time.time()
        result: list[MemoryEntry] = []

        if type is not None:
            ids = self._by_type.get(type, [])
        else:
            # Gather all ids, newest-first across types
            ids = [
                eid
                for t in MemoryType
                for eid in self._by_type[t]
            ]

        for eid in ids:
            entry = self._entries.get(eid)
            if entry is None:
                continue
            if not include_expired and entry.expires_at is not None and now >= entry.expires_at:
                continue
            result.append(entry)
            if limit > 0 and len(result) >= limit:
                break

        return result

    def get(self, id: str) -> MemoryEntry | None:
        """Retrieve a single entry by id (``None`` if missing or expired)."""
        with self._lock:
            entry = self._entries.get(id)
            if entry is None:
                return None
            if entry.is_expired:
                return None
            return entry

    def get_snapshot(self) -> dict[MemoryType, list[MemoryEntry]]:
        """Return a dict of all non-expired entries organised by type.

        Consumers receive a shallow copy — entries are immutable
        ``MemoryEntry`` objects that can safely be passed around.
        """
        with self._lock:
            self._evict_expired_locked()
            result: dict[MemoryType, list[MemoryEntry]] = {}
            for t in MemoryType:
                entries = [
                    self._entries[eid]
                    for eid in self._by_type[t]
                    if eid in self._entries
                ]
                if entries:
                    result[t] = entries
            return result

    def get_recent_commands(self, limit: int = 5) -> list[MemoryEntry]:
        """Return the *limit* most recent user commands."""
        return self.query(MemoryType.USER_COMMAND, limit=limit)

    def get_recent_actions(self, limit: int = 5) -> list[MemoryEntry]:
        """Return the *limit* most recent assistant actions."""
        return self.query(MemoryType.ASSISTANT_ACTION, limit=limit)

    def get_pending_goals(self) -> list[MemoryEntry]:
        return self.query(MemoryType.PENDING_GOAL)

    def get_pending_confirmations(self) -> list[MemoryEntry]:
        return self.query(MemoryType.PENDING_CONFIRMATION)

    # ── Singleton accessors ───────────────────────────────────────────

    def get_current_task(self) -> str | None:
        entries = self.query(MemoryType.CURRENT_TASK)
        return entries[0].content if entries else None

    def get_current_project(self) -> str | None:
        entries = self.query(MemoryType.CURRENT_PROJECT)
        return entries[0].content if entries else None

    def get_current_application(self) -> str | None:
        entries = self.query(MemoryType.CURRENT_APPLICATION)
        return entries[0].content if entries else None

    def get_current_file(self) -> str | None:
        entries = self.query(MemoryType.CURRENT_FILE)
        return entries[0].content if entries else None

    def get_current_browser_tab(self) -> str | None:
        entries = self.query(MemoryType.CURRENT_BROWSER_TAB)
        return entries[0].content if entries else None

    def get_current_folder(self) -> str | None:
        entries = self.query(MemoryType.CURRENT_FOLDER)
        return entries[0].content if entries else None

    def get_conversation_context(self) -> str | None:
        entries = self.query(MemoryType.CONVERSATION_CONTEXT)
        return entries[0].content if entries else None

    # ── Remove expired ────────────────────────────────────────────────

    def evict_expired(self) -> int:
        """Remove all expired entries.  Returns the number removed."""
        with self._lock:
            return self._evict_expired_locked()

    def _evict_expired_locked(self) -> int:
        now = time.time()
        removed = 0
        expired_ids: list[str] = []

        for eid, entry in self._entries.items():
            if entry.expires_at is not None and now >= entry.expires_at:
                expired_ids.append(eid)

        for eid in expired_ids:
            entry = self._entries.pop(eid, None)
            if entry is not None:
                try:
                    self._by_type[entry.type].remove(eid)
                except ValueError:
                    pass
                removed += 1

        if removed:
            logger.debug("WorkingMemory: evicted %d expired entries", removed)
        return removed

    def clear(self) -> int:
        """Remove all entries.  Returns the count of removed entries."""
        with self._lock:
            count = len(self._entries)
            self._entries.clear()
            for t in MemoryType:
                self._by_type[t].clear()
            return count

    # ── Summarize ─────────────────────────────────────────────────────

    def summarize(self) -> str:
        """Return a human-readable summary of the current working state."""
        with self._lock:
            self._evict_expired_locked()
            lines: list[str] = []

            task = self._singleton_content_locked(MemoryType.CURRENT_TASK)
            if task:
                lines.append(f"Task: {task}")

            project = self._singleton_content_locked(MemoryType.CURRENT_PROJECT)
            if project:
                lines.append(f"Project: {project}")

            app = self._singleton_content_locked(MemoryType.CURRENT_APPLICATION)
            if app:
                lines.append(f"Application: {app}")

            file = self._singleton_content_locked(MemoryType.CURRENT_FILE)
            if file:
                lines.append(f"File: {file}")

            tab = self._singleton_content_locked(MemoryType.CURRENT_BROWSER_TAB)
            if tab:
                lines.append(f"Browser tab: {tab}")

            folder = self._singleton_content_locked(MemoryType.CURRENT_FOLDER)
            if folder:
                lines.append(f"Folder: {folder}")

            ctx = self._singleton_content_locked(MemoryType.CONVERSATION_CONTEXT)
            if ctx:
                lines.append(f"Context: {ctx}")

            cmds = self._by_type[MemoryType.USER_COMMAND]
            if cmds:
                entry = self._entries.get(cmds[0])
                if entry and not entry.is_expired:
                    lines.append(f"Last command: {entry.content}")

            goals = [
                self._entries[eid].content
                for eid in self._by_type[MemoryType.PENDING_GOAL]
                if eid in self._entries
            ]
            if goals:
                lines.append(f"Pending goals ({len(goals)}): " + "; ".join(goals))

            confirmations = [
                self._entries[eid].content
                for eid in self._by_type[MemoryType.PENDING_CONFIRMATION]
                if eid in self._entries
            ]
            if confirmations:
                lines.append(
                    f"Pending confirmations ({len(confirmations)}): "
                    + "; ".join(confirmations)
                )

            return "\n".join(lines) if lines else "(empty)"

    def _singleton_content_locked(self, type: MemoryType) -> str | None:
        ids = self._by_type.get(type, [])
        if ids:
            entry = self._entries.get(ids[0])
            if entry and not entry.is_expired:
                return entry.content
        return None

    # ── Internal helpers ──────────────────────────────────────────────

    def _trim_list(self, type: MemoryType) -> None:
        """Trim a list-type index to its maximum size (caller holds lock)."""
        max_size = LIST_TYPE_MAX.get(type)
        if max_size is None:
            return
        ids = self._by_type[type]
        while len(ids) > max_size:
            old_id = ids.pop()
            self._entries.pop(old_id, None)

    # ── Background eviction ───────────────────────────────────────────

    def _eviction_loop(self) -> None:
        """Background loop that evicts expired entries every 60 seconds."""
        logger.info(
            "WorkingMemory: thread '%s' started",
            threading.current_thread().name,
        )
        while not self._stop.is_set():
            self.evict_expired()
            self._stop.wait(60.0)
        logger.info(
            "WorkingMemory: thread '%s' stopped",
            threading.current_thread().name,
        )
