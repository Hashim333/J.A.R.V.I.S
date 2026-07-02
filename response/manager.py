"""
response/manager.py

Response presentation coordinator.
"""

from __future__ import annotations

from typing import Any

from response.formatter import ResponseFormatter


class ResponseManager:
    """Owns presentation of Response objects for runtime surfaces."""

    def __init__(
        self,
        formatter: ResponseFormatter | None = None,
        *,
        debug: bool = False,
    ) -> None:
        self._formatter = formatter or ResponseFormatter()
        self._debug = debug

    def console_text(self, response: Any) -> str:
        """Format a Response for console output."""
        return self._formatter.console_text(response, debug=self._debug)

    def voice_text(self, response: Any) -> str:
        """Format a Response for future voice output."""
        return self._formatter.voice_text(response)

    def notification_text(self, response: Any) -> str:
        """Format a Response for future notification output."""
        return self._formatter.notification_text(response)

    def present_console(self, response: Any) -> None:
        """Print a Response to the console."""
        print(self.console_text(response))
