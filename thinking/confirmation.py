"""
thinking/confirmation.py

Builds natural-language confirmation questions from parsed intents and
entities, and classifies free-text answers as affirmative/negative.

Usage
-----
    confirm = ConfirmationEngine()
    q = confirm.build_question("close_app", {"app_name": "notepad"})
    # → "Are you sure you want me to close Notepad?"

    answer = confirm.classify_answer("yeah go ahead")
    # → "affirmative"
"""

from __future__ import annotations

import logging
import re
from typing import Any

logger = logging.getLogger(__name__)


class ConfirmationEngine:
    """Builds natural confirmation sentences and classifies yes/no answers."""

    # Responses that mean "yes, proceed"
    _AFFIRMATIVE_PHRASES: frozenset[str] = frozenset({
        "yes", "yep", "yeah", "sure", "proceed", "do it",
        "go ahead", "confirm", "absolutely", "y", "ok", "okay",
    })

    # Responses that mean "no, cancel"
    _NEGATIVE_PHRASES: frozenset[str] = frozenset({
        "no", "cancel", "stop", "never mind", "don't", "dont",
        "no thanks", "nope", "nah", "forget it", "abort",
    })

    # ── Public API ─────────────────────────────────────────────────────

    def build_question(self, intent: str, entities: dict[str, Any]) -> str:
        """Return a natural-language confirmation question.

        Parameters
        ----------
        intent:
            Parsed intent name (e.g. ``"close_app"``, ``"shutdown_windows"``).
        entities:
            Parsed entities dictionary with keys like ``app_name``,
            ``file_query``, ``drive``, etc.
        """
        builder = self._builders.get(intent)
        if builder is not None:
            return builder(entities)
        return self._generic(intent, entities)

    def classify_answer(self, text: str) -> str:
        """Classify a free-text answer.

        Returns
        -------
        ``"affirmative"``, ``"negative"``, or ``"unknown"``.
        """
        cleaned = re.sub(r"[^\w\s]", "", text).strip().casefold()

        # Check exact matches first
        if cleaned in self._AFFIRMATIVE_PHRASES:
            return "affirmative"
        if cleaned in self._NEGATIVE_PHRASES:
            return "negative"

        # Check prefix matches (e.g. "yes please" → affirmative)
        for phrase in self._AFFIRMATIVE_PHRASES:
            if cleaned.startswith(phrase):
                return "affirmative"
        for phrase in self._NEGATIVE_PHRASES:
            if cleaned.startswith(phrase):
                return "negative"

        return "unknown"

    # ── Per-intent builders (static — stored in _builders dict) ────────

    @staticmethod
    def _build_close_app(entities: dict[str, Any]) -> str:
        app = entities.get("app_name", "")
        if app:
            return f"Are you sure you want me to close {app}?"
        return "Are you sure you want me to close this application?"

    @staticmethod
    def _build_close_jarvis(entities: dict[str, Any]) -> str:
        return "Are you sure you want me to shut down? I will stop listening and close."

    @staticmethod
    def _build_shutdown_windows(entities: dict[str, Any]) -> str:
        delay = entities.get("delay_seconds")
        if delay:
            mins = int(delay // 60)
            return f"Are you sure you want me to shut down your computer in {mins} minute{'s' if mins != 1 else ''}?"
        return "Are you sure you want me to shut down your computer?"

    @staticmethod
    def _build_restart(entities: dict[str, Any]) -> str:
        delay = entities.get("delay_seconds")
        if delay:
            mins = int(delay // 60)
            return f"Are you sure you want me to restart your computer in {mins} minute{'s' if mins != 1 else ''}?"
        return "Are you sure you want me to restart your computer?"

    @staticmethod
    def _build_delete_file(entities: dict[str, Any]) -> str:
        file_query = entities.get("file_query", "")
        if file_query:
            return f"This will permanently delete {file_query}. Continue?"
        return "This will permanently delete this file. Continue?"

    @staticmethod
    def _build_format_drive(entities: dict[str, Any]) -> str:
        drive = entities.get("drive", "")
        if drive:
            return f"This will erase all data on drive {drive}. Are you sure?"
        return "This will erase all data on this drive. Are you sure?"

    @staticmethod
    def _build_kill_process(entities: dict[str, Any]) -> str:
        proc = entities.get("process", "")
        if proc:
            return f"Are you sure you want me to terminate {proc}?"
        return "Are you sure you want me to terminate this process?"

    @staticmethod
    def _build_close_all_apps(entities: dict[str, Any]) -> str:
        return "Are you sure you want me to close all open applications?"

    @staticmethod
    def _generic(intent: str, entities: dict[str, Any]) -> str:
        return "Are you sure you want me to do that?"

    # ── Builder registry ───────────────────────────────────────────────

    _builders: dict[str, Any] = {
        "close_app": _build_close_app,
        "close_jarvis": _build_close_jarvis,
        "shutdown": _build_shutdown_windows,
        "shutdown_windows": _build_shutdown_windows,
        "restart": _build_restart,
        "delete_file": _build_delete_file,
        "format_drive": _build_format_drive,
        "kill_process": _build_kill_process,
        "close_all_apps": _build_close_all_apps,
    }
