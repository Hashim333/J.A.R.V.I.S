"""
voice/pipeline/request_log.py

Structured, per-request timing log for the conversational pipeline.

A single ``PipelineRequestLog`` records every stage of one user turn and is
written out as one JSON line so the whole conversation is diagnosable from
the logs: wake latency, speech boundaries, audio duration, ASR confidence,
recognized text, the routed intent/action, and the wall time consumed by the
LLM and the execution step.

Fields (mirroring the redesign contract):

    wake_detected, speech_started, speech_ended, audio_duration_ms,
    confidence, recognized_text, intent, action_selected, llm_ms,
    execution_ms, total_ms, accepted, rejected_reason
"""
from __future__ import annotations

import json
import logging
import threading
import time
from typing import Any

logger = logging.getLogger(__name__)


class RequestLogRecord:
    """Mutable collector for one conversation turn.

    All timestamps are ``time.monotonic()`` seconds; durations are computed
    lazily at ``to_dict`` time so the caller never has to contort the
    lifecycle around blocking stages.
    """

    _FIELD_ORDER = (
        "ts", "wake_detected", "speech_started", "speech_ended",
        "audio_seconds", "confidence", "recognized_text", "intent",
        "action_selected", "llm_ms", "execution_ms", "total_ms",
        "accepted", "rejected_reason",
    )

    def __init__(self) -> None:
        self._events: dict[str, float] = {}
        self._durations_ms: dict[str, float] = {}
        self.confidence: float = 0.0
        self.recognized_text: str = ""
        self.intent: str = ""
        self.action_selected: str = ""
        self.accepted: bool = False
        self.rejected_reason: str = ""
        self._started_at: float = time.monotonic()
        self._finished_at: float | None = None

    def mark(self, event: str) -> None:
        """Record a monotonic timestamp for *event* (first write wins)."""
        self._events.setdefault(event, time.monotonic())

    def elapsed(self, name: str, started_at: float) -> None:
        """Record ``duration in ms`` for a named stage given its start time."""
        self._durations_ms[name] = (time.monotonic() - started_at) * 1000.0

    def finish(self) -> None:
        self._finished_at = time.monotonic()

    # ------------------------------------------------------------------
    # Derived timings
    # ------------------------------------------------------------------

    def _interval_ms(self, start: str, end: str) -> float:
        s, e = self._events.get(start), self._events.get(end)
        if s is None or e is None:
            return 0.0
        return (e - s) * 1000.0

    @property
    def total_ms(self) -> float:
        start = self._started_at
        end = self._finished_at if self._finished_at is not None else time.monotonic()
        return (end - start) * 1000.0

    # ------------------------------------------------------------------

    def to_dict(self) -> dict[str, Any]:
        wake = self._events.get("wake_detected")
        ss = self._events.get("speech_started")
        se = self._events.get("speech_ended")
        audio_seconds = 0.0
        if ss is not None and se is not None:
            audio_seconds = max(0.0, se - ss)

        data: dict[str, Any] = {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "wake_detected": wake,
            "speech_started": ss,
            "speech_ended": se,
            "audio_seconds": round(audio_seconds, 3),
            "confidence": round(self.confidence, 3),
            "recognized_text": self.recognized_text,
            "intent": self.intent,
            "action_selected": self.action_selected,
            "llm_ms": round(self._durations_ms.get("llm_ms", 0.0), 1),
            "execution_ms": round(self._durations_ms.get("execution_ms", 0.0), 1),
            "total_ms": round(self.total_ms, 1),
            "accepted": self.accepted,
            "rejected_reason": self.rejected_reason,
        }
        return {k: data[k] for k in self._FIELD_ORDER if k in data}

    def emit(self, logger_obj=logger, level: int = logging.INFO) -> None:
        """Emit the structured record as a single JSON line."""
        logger_obj.log(level, "REQUEST %s", json.dumps(self.to_dict(), sort_keys=False))

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<RequestLog accepted={self.accepted} text={self.recognized_text!r}>"


class RequestLogStore:
    """Append the structured records to a JSON-lines file (thread-safe)."""

    def __init__(self, path: str | None = None) -> None:
        self._path = path
        self._lock = threading.Lock()
        self._log = logger

    def write(self, record: "RequestLogRecord") -> None:
        try:
            line = json.dumps(record.to_dict())
        except (TypeError, ValueError):
            return
        if self._path is None:
            self._log.debug("REQUEST %s", line)
            return
        with self._lock:
            with open(self._path, "a", encoding="utf-8") as fh:
                fh.write(line + "\n")