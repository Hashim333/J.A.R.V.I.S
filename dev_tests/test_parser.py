"""
dev_tests/test_parser.py

Unit tests for the rule-based Parser.
"""

import unittest

from brain.parser import Parser


class TestParser(unittest.TestCase):
    """Tests for the Parser class."""

    def setUp(self) -> None:
        """Set up a new Parser instance for each test."""
        self.parser = Parser()

    def test_parse_open_app_simple(self) -> None:
        """Verify parsing of a simple 'open <app>' command."""
        command = "open notepad"
        parsed = self.parser.parse(command)
        self.assertEqual(parsed.intent, "open_app")
        self.assertEqual(parsed.entities.get("app_name"), "notepad")
        self.assertEqual(parsed.raw_text, command)
        self.assertEqual(parsed.confidence, 1.0)

    def test_parse_close_app_with_synonym(self) -> None:
        """Verify parsing of 'close <app>' using synonyms."""
        command = "quit calc"
        parsed = self.parser.parse(command)
        self.assertEqual(parsed.intent, "close_app")
        self.assertEqual(parsed.entities.get("app_name"), "calculator")

    def test_parse_with_filler_words(self) -> None:
        """Verify that filler words are correctly ignored."""
        command = "can you please open the chrome browser"
        parsed = self.parser.parse(command)
        self.assertEqual(parsed.intent, "open_app")
        self.assertEqual(parsed.entities.get("app_name"), "chrome")

    def test_parse_with_mixed_case(self) -> None:
        """Verify that parsing is case-insensitive."""
        command = "LAUNCH NOTEPAD"
        parsed = self.parser.parse(command)
        self.assertEqual(parsed.intent, "open_app")
        self.assertEqual(parsed.entities.get("app_name"), "notepad")

    def test_parse_unknown_command(self) -> None:
        """Verify that an unknown command returns intent 'unknown'."""
        command = "make me a sandwich"
        parsed = self.parser.parse(command)
        self.assertEqual(parsed.intent, "unknown")
        self.assertEqual(parsed.confidence, 0.0)
        self.assertEqual(parsed.entities, {})

    def test_parse_unknown_app(self) -> None:
        """Verify 'open <unknown_app>' is treated as an unknown command."""
        command = "open spotify"
        parsed = self.parser.parse(command)
        self.assertEqual(parsed.intent, "unknown")

    def test_parse_empty_string(self) -> None:
        """Verify that an empty string results in an 'unknown' intent."""
        parsed = self.parser.parse("")
        self.assertEqual(parsed.intent, "unknown")

    def test_parse_whitespace_only(self) -> None:
        """Verify that a whitespace-only string results in an 'unknown' intent."""
        parsed = self.parser.parse("   \t   ")
        self.assertEqual(parsed.intent, "unknown")


if __name__ == "__main__":
    unittest.main()