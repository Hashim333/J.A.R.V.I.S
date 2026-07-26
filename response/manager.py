"""
response/manager.py

Response presentation coordinator.
"""

from __future__ import annotations

from typing import Any

from config.settings import settings
from response.formatter import ResponseFormatter
from voice.manager import VoiceManager


class ResponseManager:
    """Owns presentation of Response objects for runtime surfaces."""

    def __init__(
        self,
        formatter: ResponseFormatter | None = None,
        *,
        debug: bool = False,
        voice_enabled: bool | None = None,
        voice_manager: VoiceManager | None = None,
        voice_engine: object | None = None,
    ) -> None:
        self._formatter = formatter or ResponseFormatter()
        self._debug = debug
        self._voice_enabled = (
            settings.voice_enabled if voice_enabled is None else voice_enabled
        )
        self._voice_manager = voice_manager
        self._voice_engine = voice_engine

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
        self._present_voice(response)

    def _present_voice(self, response: Any) -> None:
        if not self._voice_enabled:
            return

        message = self.voice_text(response)
        if not message:
            return

        # Prefer the VoiceEngine (non-blocking, interruptible)
        if self._voice_engine is not None:
            try:
                self._voice_engine.speak(message)
                return
            except Exception:
                pass

        # Fallback to direct VoiceManager
        if self._voice_manager is None:
            self._voice_manager = VoiceManager()
        self._voice_manager.speak(message)
