"""
response/formatter.py

Presentation-only formatting for Response objects.
"""

from __future__ import annotations

from dataclasses import is_dataclass
from typing import Any


class ResponseFormatter:
    """Convert Response objects into user-facing text."""

    _NO_STEPS_MESSAGES = {
        "Execution plan had no steps.",
        "Execution plan had no steps to run.",
    }

    def console_text(self, response: Any, *, debug: bool = False) -> str:
        """Return text suitable for the interactive console."""
        if response is None:
            return "An unexpected error occurred: no response from Brain."

        if getattr(response, "message", None) in self._NO_STEPS_MESSAGES:
            return 'I didn\'t understand that command.\nType "help" for available commands.'

        if not self._is_response_like(response):
            return f"Unstructured response: {response}"

        if response.success:
            return self._success_console_text(response)

        message = response.message or "An unknown error occurred."
        if debug and response.error:
            return f"{message}\nDetails: {response.error}"
        return message

    def voice_text(self, response: Any) -> str:
        """Return text suitable for future voice output."""
        return self._single_line(self.console_text(response, debug=False))

    def notification_text(self, response: Any) -> str:
        """Return text suitable for future desktop notifications."""
        return self._single_line(self.console_text(response, debug=False))

    def _success_console_text(self, response: Any) -> str:
        data = getattr(response, "data", {}) or {}
        intent = data.get("intent")
        first_result = self._first_step_result(data)

        if intent == "active_window":
            return f"Active window: {first_result or 'None'}"

        if intent == "list_windows":
            if not first_result:
                return "No open windows found."
            return "Open windows:\n" + "\n".join(f"  {title}" for title in first_result)

        if isinstance(first_result, bool) and first_result is False:
            return "I could not complete that action."

        return "Done."

    @staticmethod
    def _is_response_like(response: Any) -> bool:
        return is_dataclass(response) and hasattr(response, "success")

    @staticmethod
    def _first_step_result(data: dict[str, Any]) -> Any:
        results = data.get("results") or []
        if not results:
            return None
        first = results[0]
        if not isinstance(first, dict):
            return None
        return first.get("result")

    @staticmethod
    def _single_line(text: str) -> str:
        return " ".join(text.split())
