"""
response/human_sanitizer.py

Strip technical detail from arbitrary text before it reaches the user.

The Human Conversation Layer must never expose stack traces, exception
type names, timeout values, ``WinError`` numbers, Python error names,
API responses, internal file paths, model names, developer messages or
raw logs. This sanitizer detects those signatures and replaces them with
a calm, neutral fallback.
"""

from __future__ import annotations

import re
from typing import Any

_SAFE_FALLBACK = "I'm sorry, sir. Could you try again?"

# Patterns whose presence marks text as too technical to show a user.
_TECHNICAL_PATTERNS: tuple[re.Pattern[str], ...] = (
    # Tracebacks
    re.compile(r"Traceback \(most recent call last\)"),
    re.compile(r"^\s*File \"[^\"]+\"", re.MULTILINE),
    re.compile(r", line \d+, in \w+"),
    # Exception type names
    re.compile(r"(?:WinError|OSError|TimeoutError|PermissionError|"
               r"ConnectionError|RuntimeError|ValueError|KeyError|"
               r"TypeError|AttributeError|SyntaxError|Error)\b"),
    # Python module internals and API dumps
    re.compile(r"\b(?:Traceback|Exception|ModuleNotFoundError|"
               r"ImportError|IOError|asyncio)\b"),
    # Raw exceptions / reprs
    re.compile(r"^\s*[\w.]+(?:Exception|Error|Failed)\(.*\)\s*$"),
    re.compile(r"\bWinError\s*\d+\b", re.IGNORECASE),
    re.compile(r"\b(?:timed out|timeout) after \d+", re.IGNORECASE),
    re.compile(r"\bexit(?:ed)? with code \d+\b", re.IGNORECASE),
    re.compile(r"\bread(?:|ing| of)? time\.?\d*\b", re.MULTILINE),
    re.compile(r"\blevel \d+ (?:warn|error|debug)\b", re.IGNORECASE),
)


class HumanSanitizer:
    """Inspect and neutralize technical content."""

    def __init__(self, *, fallback: str = _SAFE_FALLBACK) -> None:
        self._fallback = fallback

    def sanitize(self, text: Any) -> str:
        """Return a user-safe rendering of ``text``.

        Non-strings are coerced to ``str``; technical signatures are
        replaced with a calm neutral fallback; multi-line raw output is
        collapsed to a single line.
        """
        if text is None:
            return self._fallback
        as_text = str(text)
        if self.is_technical(as_text):
            return self._fallback
        collapsed = " ".join(as_text.split()).strip()
        return collapsed or self._fallback

    def is_technical(self, text: Any) -> bool:
        """True when the text exposes low-level technical detail."""
        as_text = str(text).lower()
        if any(pattern.search(as_text) for pattern in _TECHNICAL_PATTERNS):
            return True
        # Count of exception-type tokens is a strong signal.
        hits = _EXCEPTION_TOKEN.findall(as_text)
        if len(hits) >= 2:
            return True
        return False


_EXCEPTION_TOKEN = re.compile(
    r"\b(error|exception|failed|failed to|winerror|timed out|"
    r"traceback)\b"
)