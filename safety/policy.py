"""
safety/policy.py

Central policy engine for the Safety & Confirmation Framework.
Determines whether an action requires confirmation, is protected,
or should be rejected outright.
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_CONFIG_PATH = Path(__file__).resolve().parent / "safety_config.json"


class SafetyPolicy:
    """Policy engine loaded from ``safety_config.json``."""

    def __init__(self, config_path: str | Path | None = None) -> None:
        self._path = Path(config_path) if config_path else _CONFIG_PATH
        self._config = self._load()

    # ------------------------------------------------------------------
    # Loading
    # ------------------------------------------------------------------

    def _load(self) -> dict[str, Any]:
        default = {
            "speech": {"min_confidence": 0.3, "reject_below": 0.15},
            "confirmation": {
                "required_for": [],
                "protected_operations": [],
            },
            "validation": {
                "check_file_exists": True,
                "check_app_exists": True,
                "max_file_size_mb": 500,
            },
            "audit": {"enabled": True, "log_file": "logs/audit.jsonl", "max_entries": 10000},
        }
        if not self._path.exists():
            logger.warning("Safety config not found at %s; using defaults", self._path)
            return default
        try:
            with open(self._path, encoding="utf-8") as f:
                return {**default, **json.load(f)}
        except (json.JSONDecodeError, OSError) as exc:
            logger.warning("Failed to load safety config: %s; using defaults", exc)
            return default

    # ------------------------------------------------------------------
    # Speech confidence
    # ------------------------------------------------------------------

    @property
    def min_confidence(self) -> float:
        return self._config["speech"]["min_confidence"]

    @property
    def reject_below(self) -> float:
        return self._config["speech"]["reject_below"]

    def check_speech_confidence(self, confidence: float) -> dict[str, Any]:
        """Check whether a speech confidence score is acceptable.

        Returns dict with ``accepted`` (bool), ``reason`` (str), and
        ``confidence`` (float).
        """
        if confidence >= self.min_confidence:
            return {"accepted": True, "reason": "", "confidence": confidence}
        if confidence >= self.reject_below:
            return {
                "accepted": True,
                "reason": f"Low confidence ({confidence:.2f}); will confirm before action",
                "needs_confirmation": True,
                "confidence": confidence,
            }
        return {
            "accepted": False,
            "reason": f"Confidence too low ({confidence:.2f} < {self.reject_below}); command rejected",
            "confidence": confidence,
        }

    # ------------------------------------------------------------------
    # Confirmation
    # ------------------------------------------------------------------

    @property
    def confirmation_required_for(self) -> list[str]:
        return self._config["confirmation"]["required_for"]

    @property
    def protected_operations(self) -> list[str]:
        return self._config["confirmation"]["protected_operations"]

    # ------------------------------------------------------------------
    # Safe Mode
    # ------------------------------------------------------------------

    @property
    def safe_mode_enabled(self) -> bool:
        return self._config.get("safe_mode", {}).get("enabled", False)

    @property
    def safe_mode_blocked(self) -> list[str]:
        return self._config.get("safe_mode", {}).get("blocked_actions", [])

    def is_blocked_in_safe_mode(self, action: str) -> bool:
        """Return True if *action* is blocked when Safe Mode is enabled."""
        return self.safe_mode_enabled and action in self.safe_mode_blocked

    def needs_confirmation(self, action: str, parameters: dict[str, Any] | None = None) -> bool:
        """Return True if *action* requires user confirmation."""
        return action in self.confirmation_required_for

    def is_protected(self, action: str) -> bool:
        """Return True if *action* is a protected (never auto-execute) operation."""
        return action in self.protected_operations

    def confirmation_reason(self, action: str) -> str:
        """Human-readable reason for requiring confirmation."""
        reasons = {
            "shutdown": "Shutting down the computer",
            "restart": "Restarting the computer",
            "sleep": "Putting the computer to sleep",
            "hibernate": "Hibernating the computer",
            "sign_out": "Signing out of the current session",
            "lock": "Locking the workstation",
            "delete_file": "Permanently deleting a file",
            "move_file": "Moving a file",
            "rename_file": "Renaming a file",
            "copy_file": "Copying a file",
            "close_all_apps": "Closing all running applications",
            "close_all_tabs": "Closing all browser tabs",
            "click_element": "Clicking an on-screen element",
            "format_drive": "Formatting a drive — all data will be permanently erased",
            "kill_process": "Forcefully terminating a process",
            "registry_modification": "Modifying the Windows Registry",
            "firewall_modification": "Modifying Windows Firewall rules",
            "network_scan": "Scanning network targets",
            "service_stop": "Stopping a system service",
            "taskkill": "Forcefully terminating a process via taskkill",
            "powershell_script": "Executing a PowerShell script",
            "admin_command": "Executing a command that requires administrator privileges",
        }
        return reasons.get(action, f"Executing action '{action}'")

    # ------------------------------------------------------------------
    # Validation
    # ------------------------------------------------------------------

    @property
    def check_file_exists(self) -> bool:
        return self._config["validation"]["check_file_exists"]

    @property
    def check_app_exists(self) -> bool:
        return self._config["validation"]["check_app_exists"]

    # ------------------------------------------------------------------
    # Audit
    # ------------------------------------------------------------------

    @property
    def audit_enabled(self) -> bool:
        return self._config["audit"]["enabled"]

    @property
    def audit_log_file(self) -> str:
        return self._config["audit"]["log_file"]

    @property
    def audit_max_entries(self) -> int:
        return self._config["audit"]["max_entries"]
