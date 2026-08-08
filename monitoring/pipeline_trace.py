"""
monitoring/pipeline_trace.py — always-on conversation pipeline tracing.

Every stage of the JARVIS conversation pipeline logs one structured line
on ENTRY and another on EXIT.  A stage that blocks forever shows up as an
ENTRY with no matching EXIT and the pipeline watchdog can then recover.

Fields logged per stage:

  ENTRY timestamp | thread id | queue sizes | conversation state | UI state | input
  EXIT  timestamp | duration ms | thread id | queue sizes | conversation state | UI state | output / status

The trace is always enabled (INFO level) so a stuck pipeline can be
diagnosed from logs with no configuration flag.  Queue/state getters are
registered at runtime from ``run.py``; this module never imports
application modules, so it has no import cycles and can be imported by
voice, brain, thinking, executor and services alike.
"""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable
from contextlib import contextmanager
from typing import Any

logger = logging.getLogger("trace")

_queue_getters: dict[str, Callable[[], int]] = {}
_state_getter: Callable[[], dict[str, str]] | None = None


# ---------------------------------------------------------------------------
# Registration (called once from run.py)
# ---------------------------------------------------------------------------

def register_trace_queue(name: str, getter: Callable[[], int]) -> None:
    """Register a queue-size getter so every trace line reports queue sizes."""
    _queue_getters[name] = getter


def set_trace_state(getter: Callable[[], dict[str, str]]) -> None:
    """Register a getter returning at least ``conversation`` and ``ui``."""
    global _state_getter
    _state_getter = getter


# ---------------------------------------------------------------------------
# Snapshot helpers
# ---------------------------------------------------------------------------

def _snapshot() -> str:
    parts: list[str] = []
    if _state_getter is not None:
        try:
            st = _state_getter()
            conv = st.get("conversation", "?")
            ui = st.get("ui", "?")
            parts.append(f"conv={conv} ui={ui}")
        except Exception:
            parts.append("conv=? ui=?")
    if _queue_getters:
        qs: list[str] = []
        for name, getter in _queue_getters.items():
            try:
                qs.append(f"{name}={getter()}")
            except Exception:
                qs.append(f"{name}=?")
        parts.append(f"queues={{{','.join(qs)}}}")
    return " ".join(parts)


def _now_str() -> str:
    return time.strftime("%H:%M:%S", time.localtime(time.time()))


def _thread_info() -> str:
    thread = threading.current_thread()
    return f"{thread.name}[{thread.ident}]"


# ---------------------------------------------------------------------------
# Explicit stage API
# ---------------------------------------------------------------------------

def stage_entry(stage: str, input_: Any = None) -> float:
    """Log ENTRY for *stage*; returns the monotonic start time."""
    inp = f" input={input_!r}" if input_ is not None else ""
    logger.info(
        "[TRACE] ENTER stage=%s t=%s thread=%s%s | %s",
        stage, _now_str(), _thread_info(), inp, _snapshot(),
    )
    return time.monotonic()


def stage_exit(stage: str, start: float, status: str = "OK", output: Any = None) -> None:
    """Log EXIT for *stage* given the value returned by ``stage_entry``."""
    dur = (time.monotonic() - start) * 1000
    out = f" output={output!r}" if output is not None else ""
    logger.info(
        "[TRACE] EXIT stage=%s t=%s dur=%.0fms thread=%s status=%s%s | %s",
        stage, _now_str(), dur, _thread_info(), status, out, _snapshot(),
    )


@contextmanager
def trace_stage(stage: str, input_: Any = None):
    """Context-manager wrapper over :func:`stage_entry` / :func:`stage_exit`."""
    start = stage_entry(stage, input_)
    try:
        yield
    except BaseException as exc:  # noqa: BLE001 — a traced stage never hides failures
        stage_exit(stage, start, status=f"FAIL:{type(exc).__name__}")
        raise
    else:
        stage_exit(stage, start, status="OK")


def warn_recovery(reason: str) -> None:
    """Log a timeout/recovery event with full context."""
    logger.error(
        "[TRACE] RECOVERY reason=%s t=%s thread=%s | %s",
        reason, _now_str(), _thread_info(), _snapshot(),
    )
