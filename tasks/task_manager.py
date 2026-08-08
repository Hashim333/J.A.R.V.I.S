"""
tasks/task_manager.py

Single-active-task execution manager for JARVIS.

Guarantees that only ONE task is ever active (CREATED or RUNNING) at a
time.  Accepting a new command automatically cancels the previous task,
which fires its registered cleanup callbacks (browser automation, TTS,
listeners, worker threads) and returns the backend to a consistent state.

Lifecycle::

    CREATED -> RUNNING -> SUCCESS
                       -> FAILED   (error / timeout)
                       -> CANCELLED (superseded / interrupted)

Every task carries a ``cancel_event`` (threading.Event) that is set when
the task is cancelled or fails.  Long-running work (the Executor's step
loop) checks this event at step boundaries so a superseded command aborts
promptly instead of continuing to act in the background.
"""

from __future__ import annotations

import enum
import logging
import threading
import time
import uuid
from collections.abc import Callable
from typing import Any

logger = logging.getLogger(__name__)

_TERMINAL = frozenset({"SUCCESS", "FAILED", "CANCELLED"})


class TaskStatus(enum.Enum):
    CREATED = "CREATED"
    RUNNING = "RUNNING"
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class Task:
    """A single user command tracked through its lifecycle.

    The task owns the cancellation signal (``cancel_event``) shared with
    the executor so a superseded task can stop doing work cooperatively,
    plus a list of cleanup callbacks invoked exactly once when the task
    reaches a terminal state.
    """

    __slots__ = (
        "task_id", "raw_text", "created_at", "deadline_seconds",
        "status", "cancel_event", "reason", "_cleanup", "_cleanup_done", "_lock",
    )

    def __init__(
        self,
        task_id: str,
        raw_text: str,
        deadline_seconds: float,
    ) -> None:
        self.task_id = task_id
        self.raw_text = raw_text
        self.created_at = time.monotonic()
        self.deadline_seconds = max(0.01, float(deadline_seconds))
        self.status = TaskStatus.CREATED
        self.cancel_event = threading.Event()
        self.reason: str = ""
        self._cleanup: list[Callable[[], None]] = []
        self._cleanup_done = False
        self._lock = threading.Lock()

    # ------------------------------------------------------------------
    # State queries
    # ------------------------------------------------------------------

    @property
    def is_active(self) -> bool:
        return self.status in (TaskStatus.CREATED, TaskStatus.RUNNING)

    @property
    def is_terminal(self) -> bool:
        return self.status.value in _TERMINAL

    @property
    def is_expired(self) -> bool:
        if self.status != TaskStatus.RUNNING:
            return False
        return (time.monotonic() - self.created_at) >= self.deadline_seconds

    def register_cleanup(self, callback: Callable[[], None]) -> None:
        """Register a cleanup callback invoked on terminal state (once)."""
        if not callable(callback):
            return
        with self._lock:
            if self.is_terminal:
                # Task already finished — run the callback immediately so
                # no resource is left dangling for a completed task.
                try:
                    callback()
                except Exception:
                    logger.exception("Cleanup callback failed (task already done)")
                return
            self._cleanup.append(callback)

    def _finalize(self, status: TaskStatus, reason: str = "") -> bool:
        """Transition to a terminal state and run cleanup exactly once.

        Returns True if the transition happened (task was still active).
        """
        with self._lock:
            if self.is_terminal:
                return False
            self.status = status
            self.reason = reason
            if self.status in (TaskStatus.FAILED, TaskStatus.CANCELLED):
                self.cancel_event.set()
            callbacks = list(self._cleanup)
            self._cleanup.clear()
            self._cleanup_done = True
        for callback in callbacks:
            try:
                callback()
            except Exception:
                logger.exception(
                    "Task cleanup callback failed task_id=%s", self.task_id,
                )
        return True

    def __repr__(self) -> str:  # pragma: no cover - debug helper
        return (
            f"Task(id={self.task_id!r} status={self.status.value} "
            f"raw={self.raw_text!r})"
        )


class TaskManager:
    """Owns the current/last task and enforces single-active-task semantics."""

    def __init__(
        self,
        default_deadline: float = 60.0,
        task_factory: Callable[..., Task] | None = None,
    ) -> None:
        self._default_deadline = max(0.1, float(default_deadline))
        self._task_factory = task_factory or self._new_task
        self._current: Task | None = None
        self._last: Task | None = None
        self._lock = threading.Lock()
        self._history: list[Task] = []
        self._events: list[dict[str, Any]] = []

    # ------------------------------------------------------------------
    # Factory helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _new_task(raw_text: str, deadline_seconds: float) -> Task:
        return Task(
            task_id=f"task-{uuid.uuid4().hex[:8]}",
            raw_text=raw_text,
            deadline_seconds=deadline_seconds,
        )

    def _log(self, event: str, task: Task, reason: str = "") -> None:
        entry = {
            "event": event,
            "task_id": task.task_id,
            "status": task.status.value,
            "raw_text": task.raw_text,
            "reason": reason,
            "ts": time.monotonic(),
        }
        self._events.append(entry)
        logger.info(
            "TASK %-10s id=%s status=%s raw=%r reason=%s",
            event.upper(), task.task_id, task.status.value, task.raw_text, reason,
        )

    # ------------------------------------------------------------------
    # Current-task queries
    # ------------------------------------------------------------------

    @property
    def current_task(self) -> Task | None:
        with self._lock:
            return self._current

    @property
    def last_task(self) -> Task | None:
        with self._lock:
            return self._last

    @property
    def active_task(self) -> Task | None:
        with self._lock:
            task = self._current
        if task is not None and task.is_active:
            return task
        return None

    @property
    def current_cancel_event(self) -> threading.Event | None:
        task = self.active_task
        return task.cancel_event if task is not None else None

    def is_active(self) -> bool:
        return self.active_task is not None

    @property
    def events(self) -> list[dict[str, Any]]:
        return list(self._events)

    # ------------------------------------------------------------------
    # Lifecycle API
    # ------------------------------------------------------------------

    def create_task(self, raw_text: str, deadline_seconds: float | None = None) -> Task:
        """Start a new task, cancelling any currently active one first.

        A new command always supersedes the previous task: the old task is
        cancelled (firing its cleanup callbacks and setting its
        ``cancel_event``) so the backend never runs two commands at once.
        """
        self.cancel_active(reason="superseded by new command")
        task = self._task_factory(
            raw_text, deadline_seconds if deadline_seconds is not None else self._default_deadline,
        )
        with self._lock:
            self._current = task
            self._last = task
            self._history.append(task)
        self._log("created", task)
        return task

    def start_task(self, task: Task) -> bool:
        """Move a CREATED task into RUNNING. Returns False if not possible."""
        if task.status != TaskStatus.CREATED:
            return False
        with task._lock:
            if task.status != TaskStatus.CREATED:
                return False
            task.status = TaskStatus.RUNNING
        self._log("started", task)
        return True

    def mark_success(self, task: Task) -> bool:
        if not task._finalize(TaskStatus.SUCCESS):
            return False
        self._clear_if_current(task)
        self._log("completed", task)
        return True

    def mark_failed(self, task: Task, reason: str = "failed") -> bool:
        if not task._finalize(TaskStatus.FAILED, reason=reason):
            return False
        self._clear_if_current(task)
        self._log("failed", task, reason)
        return True

    def cancel(self, task: Task, reason: str = "cancelled") -> bool:
        if not task._finalize(TaskStatus.CANCELLED, reason=reason):
            return False
        self._clear_if_current(task)
        self._log("cancelled", task, reason)
        return True

    def cancel_active(self, reason: str = "cancelled") -> bool:
        """Cancel the active task (if any). Returns True if one was cancelled."""
        task = self.active_task
        if task is None:
            return False
        return self.cancel(task, reason)

    def mark_timeout(self, task: Task) -> bool:
        """Timeouts are failures that also abort any still-running worker."""
        return self.mark_failed(task, reason="timeout")

    def check_timeouts(self) -> list[Task]:
        """Mark any expired RUNNING task as FAILED(timeout).

        The executor sets ``cancel_event`` on the brain timeout path, so
        a timed-out task's background worker also stops at its next step
        boundary.  This is belt-and-braces for plans whose deadline fires
        before the brain's own 20s timeout.
        """
        with self._lock:
            expired = [t for t in self._history if t.is_active and t.is_expired]
        for task in expired:
            self.mark_timeout(task)
        return expired

    def register_cleanup(self, task: Task, callback: Callable[[], None]) -> None:
        task.register_cleanup(callback)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _clear_if_current(self, task: Task) -> None:
        with self._lock:
            if self._current is task:
                self._current = None
