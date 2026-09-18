"""
response/formatter.py

Presentation-only formatting for Response objects.
"""

from __future__ import annotations

from dataclasses import is_dataclass
from typing import Any

from models.task_result import TaskResult


class ResponseFormatter:
    """Convert Response objects into user-facing text."""

    _NO_STEPS_MESSAGES = {
        "Execution plan had no steps.",
        "Execution plan had no steps to run.",
    }

    _GENERIC_SUCCESS_MESSAGES = (
        "done.",
        "action completed.",
        "all 1 step(s) executed successfully.",
        "all 2 step(s) executed successfully.",
        "no response from executor.",
        "cancelled.",
    )

    def console_text(self, response: Any, *, debug: bool = False) -> str:
        """Return text suitable for the interactive console."""
        if response is None:
            return "An unexpected error occurred: no response from Brain."

        if getattr(response, "message", None) in self._NO_STEPS_MESSAGES:
            return 'I didn\'t understand that command.\nType "help" for available commands.'

        if not self._is_response_like(response):
            return f"Unstructured response: {response}"

        task_result = getattr(response, "task_result", None)
        diagnostic = getattr(response, "diagnostic", None)

        if response.success and task_result == TaskResult.SUCCESS:
            return self._success_console_text(response)

        # Clarification / confirmation requests
        if getattr(response, "needs_clarification", False):
            q = getattr(response, "clarification_question", "") or (response.message or "")
            return q

        # --- Failure modes ---
        message = response.message or "An unknown error occurred."

        if task_result == TaskResult.UNSUPPORTED:
            return message or (
                "That request isn't something I can execute yet. "
                "Rephrase it, or ask me what skills are missing to see the roadmap."
            )

        if task_result == TaskResult.INTERNAL_ERROR:
            # ARCH-002 / NO INTERNAL ERROR SPEECH: a raw internal
            # failure must never reach the user face.  Only debug
            # surfaces get the technical detail.
            if debug and diagnostic:
                base = (
                    f"Internal error: {message}"
                    f"\n  Component: {diagnostic.component}"
                    f"\n  Exception: {diagnostic.exception}"
                )
            else:
                base = "I ran into an unexpected problem. Please try again."
            return base

        if task_result == TaskResult.FAILED:
            return self._format_failure(response, diagnostic, debug=debug)

        # Fallback for any unclassified failure
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

        # Prefer the response's own message. It is informative for chat /
        # LLM replies and for actions whose handler returned a real
        # message (e.g. "Chrome opened."). Only fall back to "Done." when
        # the message is a generic placeholder.
        message = (getattr(response, "message", "") or "").strip()
        if message and not self._is_generic_success(message):
            return message

        return self._fallback_success_message(intent, data)

    @classmethod
    def _is_generic_success(cls, message: str) -> bool:
        lower = message.casefold()
        if lower in cls._GENERIC_SUCCESS_MESSAGES:
            return True
        if lower.startswith("step ") and lower.endswith(" completed."):
            return True
        if lower == "all steps executed.":
            return True
        return False

    @classmethod
    def _fallback_success_message(cls, intent: Any, data: dict[str, Any]) -> str:
        """Generate a meaningful success line when the handler gave none."""
        if intent == "open_app":
            app = data.get("app_name") or data.get("display_name", "")
            return f"{app} is now open." if app else "Application opened."
        if intent == "open_website":
            site = data.get("website", "")
            return f"Opened {site}." if site else "Website opened."
        if intent == "search":
            query = data.get("query", "")
            return f"Searched for '{query}'." if query else "Search results opened."
        if intent == "play_music":
            query = data.get("query", "")
            return f"Playing '{query}'." if query else "Playing music."
        return "Understood."

    def _format_failure(self, response: Any, diagnostic: Any, *, debug: bool = False) -> str:
        """Render a failed task as a short, natural user-facing response.

        ARCH-002 / NO INTERNAL ERROR SPEECH: execution metadata (component
        names, exception texts, ``Task:`` / ``Result: FAILED`` scaffolding,
        raw diagnostics) must never be spoken or printed as the user
        response.  ``message`` is surfaced as a calm short sentence and the
        technical detail is only appended when ``debug`` is requested.
        """
        message = (response.message or "").strip()
        if not message or message.casefold() == "unknown task":
            return "I couldn't complete that action."
        parts = [message]
        if debug:
            if diagnostic is not None:
                parts.append(f"Component: {diagnostic.component}")
                reason = diagnostic.reason or diagnostic.exception or "Unknown"
                parts.append(f"Reason: {reason}")
                if diagnostic.recovery_attempted:
                    parts.append(f"Recovery: {diagnostic.recovery_attempted}")
            parts.append("Result: FAILED")
        return "\n".join(parts)

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
