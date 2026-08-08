from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable

logger = logging.getLogger(__name__)


class Watchdog:
    """Monitors a subsystem heartbeat and triggers a callback if it stalls."""

    def __init__(
        self,
        name: str,
        timeout: float = 15.0,
        on_stall: Callable[[str], None] | None = None,
    ) -> None:
        self.name = name
        self._timeout = timeout
        self._on_stall = on_stall
        self._last_heartbeat = time.monotonic()
        self._lock = threading.Lock()
        self._running = False
        self._thread: threading.Thread | None = None
        self._stalled = False

    def start(self) -> None:
        with self._lock:
            if self._running:
                return
            self._running = True
            self._last_heartbeat = time.monotonic()
            self._stalled = False
        self._thread = threading.Thread(target=self._monitor, daemon=True)
        self._thread.start()
        logger.info("Watchdog[%s] started (timeout=%.1fs)", self.name, self._timeout)

    def stop(self) -> None:
        with self._lock:
            if not self._running:
                return
            self._running = False
        logger.info("Watchdog[%s] stopped", self.name)
        thread = self._thread
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=1.0)
            if thread.is_alive():
                logger.debug("Watchdog[%s] monitor thread did not join", self.name)
        self._thread = None

    def kick(self) -> None:
        with self._lock:
            self._last_heartbeat = time.monotonic()
            if self._stalled:
                self._stalled = False
                logger.info("Watchdog[%s] recovered after stall", self.name)

    def _monitor(self) -> None:
        while True:
            with self._lock:
                if not self._running:
                    return
                elapsed = time.monotonic() - self._last_heartbeat
                stalled = elapsed > self._timeout
                if stalled and not self._stalled:
                    self._stalled = True
                    logger.error(
                        "Watchdog[%s] STALL detected — %.1fs since last heartbeat",
                        self.name, elapsed,
                    )
                    if self._on_stall:
                        try:
                            self._on_stall(self.name)
                        except Exception as exc:
                            logger.error("Watchdog[%s] stall callback failed: %s", self.name, exc)
            time.sleep(self._timeout / 4.0)


class WatchdogManager:
    """Manages multiple watchdogs and coordinates stall responses."""

    def __init__(self) -> None:
        self._watchdogs: dict[str, Watchdog] = {}
        self._lock = threading.Lock()

    def add(
        self,
        name: str,
        timeout: float = 15.0,
        on_stall: Callable[[str], None] | None = None,
    ) -> Watchdog:
        wd = Watchdog(name=name, timeout=timeout, on_stall=on_stall or self._on_stall)
        with self._lock:
            self._watchdogs[name] = wd
        wd.start()
        return wd

    def kick(self, name: str) -> None:
        wd = self._watchdogs.get(name)
        if wd is not None:
            wd.kick()

    def stop_all(self) -> None:
        with self._lock:
            for wd in self._watchdogs.values():
                wd.stop()
            self._watchdogs.clear()

    def _on_stall(self, name: str) -> None:
        logger.critical("WatchdogManager: subsystem '%s' is unresponsive", name)
