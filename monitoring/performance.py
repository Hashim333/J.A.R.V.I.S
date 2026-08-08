from __future__ import annotations

import functools
import logging
import threading
import time
from collections.abc import Callable
from typing import Any

logger = logging.getLogger(__name__)


def log_duration(logger_override: logging.Logger | None = None) -> Callable:
    """Decorator that logs start, end, duration, thread, and success/failure."""
    def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
        @functools.wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            _logger = logger_override or logging.getLogger(func.__module__)
            thread_name = threading.current_thread().name
            _logger.debug(
                "[PERF] %s START | thread=%s", func.__qualname__, thread_name,
            )
            start = time.monotonic()
            try:
                result = func(*args, **kwargs)
                elapsed = (time.monotonic() - start) * 1000
                _logger.debug(
                    "[PERF] %s END | duration=%.0fms thread=%s success=True",
                    func.__qualname__, elapsed, thread_name,
                )
                return result
            except Exception as exc:
                elapsed = (time.monotonic() - start) * 1000
                _logger.error(
                    "[PERF] %s END | duration=%.0fms thread=%s success=False error=%s",
                    func.__qualname__, elapsed, thread_name, exc,
                )
                raise
        return wrapper
    return decorator
