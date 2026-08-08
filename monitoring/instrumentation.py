"""
monitoring/instrumentation.py — non-invasive diagnostic telemetry.

Log-only instrumentation. Does NOT change any behavior.

Enable via ``JARVIS_DIAG=1`` (default off) so production behavior is
byte-for-byte unchanged when the flag is absent.

Provides:
  - ``@timed(name)`` / ``Timer``: START/END + duration(ms) + thread id
  - ``register_queue()``: sample queue sizes in the periodic snapshot
  - ``install()``: start the background sampler (CPU, RSS, threads, queues)
  - ``ui_tick()``: call from a UI-thread QTimer to measure UI responsiveness
    (heartbeat tick rate as a FPS proxy) and detect event-loop stalls.
"""

from __future__ import annotations

import functools
import logging
import os
import threading
import time
from collections.abc import Callable
from typing import Any

logger = logging.getLogger("diag")

_ENABLED = os.environ.get("JARVIS_DIAG", "").strip() == "1"

_queues: dict[str, Callable[[], int]] = {}
_queues_lock = threading.Lock()
_sampler: "Sampler | None" = None
_sampler_lock = threading.Lock()

_ui_count = 0
_ui_count_lock = threading.Lock()
_ui_prev = time.monotonic()


class Timer:
    """Context manager that logs START/END + duration + thread id."""

    def __init__(self, name: str) -> None:
        self._name = name
        self._start = 0.0

    def __enter__(self) -> "Timer":
        if _ENABLED:
            self._start = time.monotonic()
            logger.info(
                "[DIAG] TASK START | task=%s thread=%s tid=%d",
                self._name, threading.current_thread().name,
                threading.get_ident(),
            )
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        if _ENABLED:
            elapsed = (time.monotonic() - self._start) * 1000
            status = "FAIL" if exc_type is not None else "OK"
            logger.info(
                "[DIAG] TASK END   | task=%s thread=%s tid=%d status=%s duration=%.0fms",
                self._name, threading.current_thread().name,
                threading.get_ident(), status, elapsed,
            )


def timed(name: str) -> Callable:
    """Decorator wrapper around :class:`Timer`."""
    def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
        @functools.wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            if not _ENABLED:
                return func(*args, **kwargs)
            with Timer(name):
                return func(*args, **kwargs)
        return wrapper
    return decorator


def register_queue(name: str, source: Any) -> None:
    """Register a queue-like object (has qsize()) or a size callable."""
    if not _ENABLED:
        return
    if callable(source):
        getter = source
    elif hasattr(source, "qsize"):
        getter = lambda: source.qsize()  # noqa: E731
    else:
        logger.warning("[DIAG] queue %r not supported for sampling", name)
        return
    with _queues_lock:
        _queues[name] = getter


def ui_tick() -> None:
    """Call from a QTimer on the UI thread to measure responsiveness."""
    if not _ENABLED:
        return
    with _ui_count_lock:
        global _ui_count
        _ui_count += 1


class Sampler(threading.Thread):
    """Background thread that periodically logs a resource snapshot."""

    def __init__(self, interval: float = 2.0) -> None:
        super().__init__(name="diag-sampler", daemon=True)
        self._interval = interval
        self._stop = threading.Event()

    def stop(self) -> None:
        self._stop.set()

    def run(self) -> None:
        while not self._stop.wait(self._interval):
            try:
                self._snapshot()
            except Exception as exc:
                logger.debug("[DIAG] snapshot failed: %s", exc)

    def _snapshot(self) -> None:
        with _queues_lock:
            qs = {name: getter() for name, getter in _queues.items()}
        threads = sorted(
            f"{t.name}[{t.ident}]{'d' if t.daemon else ''}{'!' if not t.is_alive() else ''}"
            for t in threading.enumerate()
        )
        cpu = rss = 0.0
        try:
            import psutil
            proc = psutil.Process()
            rss = proc.memory_info().rss / 1024 / 1024
            cpu = psutil.cpu_percent(interval=None)
        except Exception:
            pass

        with _ui_count_lock:
            global _ui_prev, _ui_count
            now = time.monotonic()
            tick_rate = _ui_count / (now - _ui_prev) if now > _ui_prev else 0.0
            _ui_prev = now
            _ui_count = 0

        logger.info(
            "[DIAG] SNAPSHOT | cpu=%.0f%% rss=%.0fMB ui_tick=%.1f/s "
            "threads=%d queues=%s threadlist=%s",
            cpu, rss, tick_rate, len(threads), qs, "|".join(threads),
        )


def install(queues: dict[str, Any] | None = None, interval: float = 2.0) -> None:
    """Enable instrumentation and start the sampler (idempotent)."""
    if not _ENABLED:
        logger.warning("[DIAG] JARVIS_DIAG != 1 — instrumentation disabled")
        return
    if queues:
        for name, source in queues.items():
            register_queue(name, source)
    with _sampler_lock:
        global _sampler
        if _sampler is not None:
            return
        _sampler = Sampler(interval=interval)
        _sampler.start()
    logger.info("[DIAG] instrumentation installed (interval=%.1fs)", interval)


def enabled() -> bool:
    return _ENABLED
