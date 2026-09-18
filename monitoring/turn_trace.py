"""One-turn runtime trace for the voice conversation pipeline.

The trace is intentionally tiny and self-disabling: it records the first
real turn after startup, then stops. Each line uses the fixed ``[TURN]``
prefix requested by the forensic runbook so launcher-captured stderr is
enough to identify the last reached stage.
"""
from __future__ import annotations

import logging
import threading
import time
from typing import Any

logger = logging.getLogger("turn")

_lock = threading.RLock()
_turn_id = 0
_active = True
_completed = False
_seen_stages: set[str] = set()


def _thread_label() -> str:
    thread = threading.current_thread()
    return f"{thread.name}[{thread.ident}]"


def start_turn(gen: int | None = None) -> int:
    global _turn_id, _active
    with _lock:
        if _completed:
            return _turn_id
        if _turn_id == 0:
            _turn_id = int(gen or 1)
            _active = True
        return _turn_id


def active() -> bool:
    with _lock:
        return _active and not _completed


def mark(stage: str, *, gen: int | None = None, **fields: Any) -> None:
    """Log one trace stage for the active first turn only."""
    global _active, _completed
    with _lock:
        if _completed:
            return
        if _turn_id == 0:
            if stage != "LISTENING_READY":
                return
            start_turn(gen)
        if not _active:
            return
        repeatable = {"LISTENING_READY"}
        if stage in _seen_stages and stage not in repeatable:
            return
        _seen_stages.add(stage)
        turn = _turn_id

    safe_fields = " ".join(
        f"{key}={value!r}" for key, value in fields.items()
        if value is not None
    )
    logger.info(
        "[TURN] %s timestamp=%.3f turn=%s gen=%s thread=%s%s%s",
        stage,
        time.time(),
        turn,
        gen if gen is not None else "-",
        _thread_label(),
        " " if safe_fields else "",
        safe_fields,
    )
    if stage == "LISTENING_READY" and "MIC_REARM" in _seen_stages:
        with _lock:
            _active = False
            _completed = True


def reset_for_tests() -> None:
    global _turn_id, _active, _completed
    with _lock:
        _turn_id = 0
        _active = True
        _completed = False
        _seen_stages.clear()
