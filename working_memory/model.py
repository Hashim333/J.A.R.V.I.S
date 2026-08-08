"""
working_memory/model.py — Data model for short-term memory entries.

All memory entries are frozen dataclasses — once created they are never
mutated (replace an entry by adding a new one).
"""

from __future__ import annotations

import dataclasses
import enum
import time
from typing import Any


class MemoryType(enum.Enum):
    """Categorises every memory entry in working memory."""

    USER_COMMAND = "user_command"
    ASSISTANT_ACTION = "assistant_action"
    PENDING_GOAL = "pending_goal"
    PENDING_CONFIRMATION = "pending_confirmation"
    CURRENT_TASK = "current_task"
    CURRENT_PROJECT = "current_project"
    CURRENT_APPLICATION = "current_application"
    CURRENT_FILE = "current_file"
    CURRENT_BROWSER_TAB = "current_browser_tab"
    CURRENT_FOLDER = "current_folder"
    CONVERSATION_CONTEXT = "conversation_context"


# Singleton types — at most one entry per type may exist at a time.
SINGLETON_TYPES: frozenset[MemoryType] = frozenset({
    MemoryType.CURRENT_TASK,
    MemoryType.CURRENT_PROJECT,
    MemoryType.CURRENT_APPLICATION,
    MemoryType.CURRENT_FILE,
    MemoryType.CURRENT_BROWSER_TAB,
    MemoryType.CURRENT_FOLDER,
    MemoryType.CONVERSATION_CONTEXT,
})

# List types — entries accumulate up to a maximum count.
LIST_TYPE_MAX: dict[MemoryType, int] = {
    MemoryType.USER_COMMAND: 20,
    MemoryType.ASSISTANT_ACTION: 20,
    MemoryType.PENDING_GOAL: 50,
    MemoryType.PENDING_CONFIRMATION: 20,
}


@dataclasses.dataclass(frozen=True)
class MemoryEntry:
    """An indivisible unit of short-term memory.

    Parameters
    ----------
    id:
        Unique identifier for this entry (UUID string).
    type:
        The category of memory (user command, action, goal, ...).
    content:
        The payload — a human-readable string describing the memory.
    timestamp:
        When this entry was created (``time.time()``).
    expires_at:
        Optional expiry timestamp.  ``None`` means the entry is persistent
        and will never be auto-evicted.
    metadata:
        Optional key-value bag for structured data (e.g. ``{"pid": 1234}``).
    """
    id: str
    type: MemoryType
    content: str
    timestamp: float
    expires_at: float | None = None
    metadata: dict[str, Any] = dataclasses.field(default_factory=dict)

    @property
    def is_expired(self) -> bool:
        if self.expires_at is None:
            return False
        return time.time() >= self.expires_at

    @property
    def age_seconds(self) -> float:
        return time.time() - self.timestamp
