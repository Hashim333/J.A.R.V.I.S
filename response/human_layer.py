"""
response/human_layer.py

Human Conversation Layer.

A reusable gateway that sits between every internal module and the user.
Its single responsibility is to convert internal errors, states and
failures into calm, natural human speech, and to ensure that no technical
detail ever reaches the user (no stack traces, exception type names,
timeout values, ``WinError`` numbers, Python error names, API responses,
internal file paths, model names, developer messages or raw logs).

Full technical detail is routed to debug logs only, never to the
user-facing message.

Usage (importable by all present and future components):

    from response.human_layer import HumanResponseManager

    layer = HumanResponseManager()
    text = layer.humanize("TimeoutError")           # natural apology
    text = layer.translate(exception_or_state)      # auto-classify
    text = layer.sanitize(raw_developer_text)       # strip technicals

The layer is intentionally dependency-light and fully injectable so it
can be unit-tested without touching the network, hardware or TTS.
"""

from __future__ import annotations

import re
from typing import Any, Callable, Optional

from response.human_message import HUMAN_MESSAGES, SAFE_FALLBACK
from response.human_sanitizer import HumanSanitizer


class HumanResponseManager:
    """Converts internal states/failures into natural human speech.

    Do not expose stack traces, exception names, timeout values,
    WinError numbers, paths, model names or raw logs to the user.
    """

    def __init__(
        self,
        *,
        sanitizer: Optional[HumanSanitizer] = None,
        messages: Optional[dict[str, str]] = None,
        logger: Optional[Callable[[str], None]] = None,
        debug: bool = False,
    ) -> None:
        self._sanitizer = sanitizer or HumanSanitizer()
        self._messages = dict(messages or HUMAN_MESSAGES)
        self._logger = logger or _null_logger
        self._debug = debug

    # -- Public API -----------------------------------------------------

    def humanize(self, state: Any, *, detail: Any = None, **fmt: Any) -> str:
        """Map an internal state key to a natural, user-safe message.

        ``detail`` is never shown to the user; it is only recorded in the
        debug log so engineers can investigate while JARVIS stays calm.
        """
        key = self._key_for(state)
        template = self._messages.get(key, SAFE_FALLBACK)
        if key and not key in HUMAN_MESSAGES:
            self._log_technical(
                f"Unmapped internal state {key!r}, unknown fallback; detail={detail!r}"
            )
        else:
            self._log_technical(
                f"Humanized state {key!r}: detail={detail!r}, fmt={fmt!r}"
            )
        try:
            return template.format(**fmt)
        except (KeyError, IndexError):
            return template

    def translate(self, error: Any) -> str:
        """Auto-classify an exception or state and return human text."""
        return self.humanize(error)

    def sanitize(self, text: Any) -> str:
        """Neutralize technical detail in arbitrary text before it reaches UI/TTS."""
        return self._sanitizer.sanitize(text)

    def with_detail_logged(self, log: Callable[[str], None]) -> "HumanResponseManager":
        self._logger = log or _null_logger
        return self

    # -- Internals ------------------------------------------------------

    def _key_for(self, state: Any) -> str:
        from response.human_message import classify

        key = classify(state)
        if key:
            return key
        if isinstance(state, str):
            return state
        return ""

    def _log(self, message: str) -> None:
        if not self._debug:
            return
        try:
            self._logger(message)
        except Exception:
            pass

    def _log_technical(self, message: str) -> None:
        self._log(message)


def _null_logger(message: str) -> None:
    pass