"""
safety/audit.py

Audit log recording every executed command, confirmation, validation
result, and safety decision. Persisted as newline-delimited JSON.
"""

from __future__ import annotations

import json
import logging
import os
import time
from pathlib import Path
from typing import Any

from safety.policy import SafetyPolicy

logger = logging.getLogger(__name__)


class AuditLog:
    """Thread-safe audit log backed by a JSONL file.

    Usage::

        audit = AuditLog()
        audit.record_command("shutdown", {"delay": 0}, confirmed=True)
        audit.record_validation("open_file", True, "File exists")
        audit.record_rejection("low confidence", 0.05)

    The log file is pruned to ``max_entries`` on each write.
    """

    def __init__(self, policy: SafetyPolicy | None = None) -> None:
        self._policy = policy or SafetyPolicy()
        self._log_file = Path(self._policy.audit_log_file)
        self._max_entries = self._policy.audit_max_entries
        self._enabled = self._policy.audit_enabled

        if self._enabled:
            self._log_file.parent.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------
    # Recording
    # ------------------------------------------------------------------

    def record(
        self,
        event_type: str,
        data: dict[str, Any],
    ) -> None:
        if not self._enabled:
            return
        entry = {
            "timestamp": time.time(),
            "iso": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime()),
            "type": event_type,
            **data,
        }
        try:
            with open(self._log_file, "a", encoding="utf-8") as f:
                f.write(json.dumps(entry, default=str) + "\n")
            self._prune()
        except OSError as exc:
            logger.warning("Audit log write failed: %s", exc)

    def record_command(
        self,
        intent: str,
        raw_text: str,
        step_actions: list[str],
        confirmed: bool = False,
        confidence: float = 1.0,
        success: bool = True,
        details: str = "",
        validation_failed: str = "",
        validation_message: str = "",
        fallback_rejected: str = "",
        parameter_details: str = "",
    ) -> None:
        self.record("command", {
            "intent": intent,
            "raw_text": raw_text,
            "steps": step_actions,
            "confirmed": confirmed,
            "confidence": confidence,
            "success": success,
            "details": details,
            "validation_failed": validation_failed,
            "validation_message": validation_message,
            "fallback_rejected": fallback_rejected,
            "parameter_details": parameter_details,
        })

    def record_confirmation(self, action: str, granted: bool, reason: str = "") -> None:
        self.record("confirmation", {
            "action": action,
            "granted": granted,
            "reason": reason,
        })

    def record_validation(
        self,
        action: str,
        passed: bool,
        message: str,
    ) -> None:
        self.record("validation", {
            "action": action,
            "passed": passed,
            "message": message,
        })

    def record_rejection(self, reason: str, confidence: float = 0.0) -> None:
        self.record("rejection", {
            "reason": reason,
            "confidence": confidence,
        })

    # ------------------------------------------------------------------
    # Querying
    # ------------------------------------------------------------------

    def recent_entries(self, count: int = 10) -> list[dict[str, Any]]:
        """Return the *count* most recent audit entries."""
        if not self._log_file.exists():
            return []
        try:
            with open(self._log_file, encoding="utf-8") as f:
                lines = f.readlines()
            entries = [json.loads(line) for line in lines if line.strip()]
            return entries[-count:]
        except (OSError, json.JSONDecodeError) as exc:
            logger.warning("Audit log read failed: %s", exc)
            return []

    def command_history(self, count: int = 10) -> list[dict[str, Any]]:
        """Return the *count* most recent command entries."""
        return [
            e for e in self.recent_entries(count * 5)
            if e.get("type") == "command"
        ][-count:]

    # ------------------------------------------------------------------
    # Maintenance
    # ------------------------------------------------------------------

    def _prune(self) -> None:
        if not self._log_file.exists():
            return
        try:
            with open(self._log_file, encoding="utf-8") as f:
                lines = f.readlines()
            if len(lines) <= self._max_entries:
                return
            with open(self._log_file, "w", encoding="utf-8") as f:
                f.writelines(lines[-self._max_entries:])
        except OSError as exc:
            logger.warning("Audit log prune failed: %s", exc)

    def clear(self) -> None:
        """Delete all audit entries."""
        try:
            if self._log_file.exists():
                self._log_file.unlink()
        except OSError as exc:
            logger.warning("Audit log clear failed: %s", exc)
