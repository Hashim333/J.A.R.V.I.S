from __future__ import annotations

import logging
import threading
import time
from typing import Any, Callable

logger = logging.getLogger(__name__)


class ShutdownManager:
    PHASES: list[tuple[str, float]] = [
        ("stop_listening", 2.0),
        ("stop_wake_word", 2.0),
        ("stop_conversation", 1.0),
        ("stop_browser", 3.0),
        ("stop_system_awareness", 3.0),
        ("stop_world_state", 3.0),
        ("stop_working_memory", 2.0),
        ("stop_monitors", 5.0),
        ("stop_watchdogs", 2.0),
        ("join_worker_threads", 5.0),
        ("close_windows", 2.0),
    ]

    def __init__(self) -> None:
        self._hooks: dict[str, list[Callable[[], None]]] = {name: [] for name, _ in self.PHASES}
        self._threads: list[threading.Thread] = []

    def on(self, phase: str, hook: Callable[[], None]) -> None:
        if phase in self._hooks:
            self._hooks[phase].append(hook)
        else:
            logger.warning("Shutdown phase %r does not exist — hook dropped", phase)

    def register_thread(self, thread: threading.Thread) -> None:
        self._threads.append(thread)

    def shutdown(self) -> float:
        start = time.monotonic()
        logger.info("Shutdown starting")
        for phase_name, timeout in self.PHASES:
            phase_start = time.monotonic()
            for hook in self._hooks.get(phase_name, []):
                try:
                    hook()
                except Exception as exc:
                    logger.warning("Shutdown phase %s hook failed: %s", phase_name, exc)
            elapsed = time.monotonic() - phase_start
            logger.info(
                "Shutdown phase %s completed in %.0fms",
                phase_name, elapsed * 1000,
            )

        self._join_threads()

        total = time.monotonic() - start
        logger.info("Shutdown completed in %.1fs", total)
        return total

    def _join_threads(self) -> None:
        for t in self._threads:
            if t is threading.current_thread():
                continue
            if t.is_alive():
                t.join(timeout=2.0)
                if t.is_alive():
                    logger.warning("Thread %s did not join within 2s timeout", t.name)
