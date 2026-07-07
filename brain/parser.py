"""
brain/parser.py

Parser turns raw user text into a ParsedCommand using rule-based matching.
"""

from __future__ import annotations

import re

from brain.parsed_command import ParsedCommand


class Parser:
    """
    A stateless, rule-based intent parser.
    Its only public method is `parse(text)`.
    """

    _APP_SYNONYMS: dict[str, str] = {
        "notepad": "notepad",
        "calculator": "calculator",
        "calc": "calculator",
        "google chrome": "chrome",
        "chrome": "chrome",
        "chrome browser": "chrome",
    }

    _APP_INTENTS: dict[str, tuple[str, ...]] = {
        "open_app": ("open", "launch", "run", "start"),
        "close_app": ("close", "quit", "exit", "terminate"),
    }

    _FILLER_WORDS: frozenset[str] = frozenset(
        {
            "please",
            "kindly",
            "can you",
            "could you",
            "would you",
            "a",
            "the",
            "an",
        }
    )

    def parse(self, text: str) -> ParsedCommand:
        """
        Parses raw text into a structured command.

        Args:
            text: The raw user command string.

        Returns:
            A ParsedCommand object. If the command is not understood,
            the intent will be 'unknown'.
        """
        normalized = self._normalize(text)
        if not normalized:
            return self._unknown(text)

        # Attempt to parse each category of command in order.
        parsed = self._parse_app_command(normalized, text)

        return parsed or self._unknown(text)

    def _parse_app_command(self, normalized: str, raw_text: str) -> ParsedCommand | None:
        """Parses commands related to application management."""
        for intent, synonyms in self._APP_INTENTS.items():
            for synonym in synonyms:
                # Match commands like "open notepad" or "close chrome"
                match = re.match(rf"^{re.escape(synonym)}\s+(.+)", normalized)
                if match:
                    app_phrase = match.group(1).strip()
                    app_name = self._APP_SYNONYMS.get(app_phrase)
                    if app_name:
                        return ParsedCommand(
                            raw_text=raw_text,
                            intent=intent,
                            entities={"app_name": app_name},
                        )
        return None

    def _normalize(self, text: str) -> str:
        """
        Converts text to a canonical form for parsing: lowercase, no
        punctuation, and common filler words removed.
        """
        if not text:
            return ""

        # Lowercase and remove punctuation
        normalized = text.casefold()
        normalized = re.sub(r"[^\w\s]", "", normalized)

        # Build a regex pattern to match only whole words/phrases.
        # The `\b` anchors ensure that "a" isn't removed from "notepad".
        # Sorting by length ensures "can you" is matched before "can" or "you".
        sorted_fillers = sorted(self._FILLER_WORDS, key=len, reverse=True)
        pattern = r"\b(" + "|".join(re.escape(word) for word in sorted_fillers) + r")\b"
        normalized = re.sub(pattern, "", normalized)

        # Collapse repeated whitespace
        normalized = " ".join(normalized.split())

        return normalized

    @staticmethod
    def _unknown(raw_text: str) -> ParsedCommand:
        """Creates a standard ParsedCommand for unrecognized input."""
        return ParsedCommand(
            raw_text=raw_text,
            intent="unknown",
            confidence=0.0,
            entities={},
        )