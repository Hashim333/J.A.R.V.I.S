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

    # --- Profile extraction ---

    def test_parse_open_chrome_with_profile(self) -> None:
        """Verify extraction of profile from 'open chrome with profile <name>'."""
        parsed = self.parser.parse("open chrome with profile work")
        self.assertEqual(parsed.intent, "open_app")
        self.assertEqual(parsed.entities.get("app_name"), "chrome")
        self.assertEqual(parsed.entities.get("profile"), "work")

    def test_parse_open_chrome_with_profile_and_filler(self) -> None:
        """Profile extraction works with filler words."""
        parsed = self.parser.parse("please open chrome with profile gaming")
        self.assertEqual(parsed.intent, "open_app")
        self.assertEqual(parsed.entities.get("app_name"), "chrome")
        self.assertEqual(parsed.entities.get("profile"), "gaming")

    def test_parse_non_chrome_app_with_profile(self) -> None:
        """Parser extracts profile for any app (it is up to downstream to use it)."""
        parsed = self.parser.parse("open notepad with profile work")
        self.assertEqual(parsed.intent, "open_app")
        self.assertEqual(parsed.entities.get("app_name"), "notepad")
        self.assertEqual(parsed.entities.get("profile"), "work")

    def test_parse_open_chrome_no_profile(self) -> None:
        """Opening chrome without a profile should not set a profile entity."""
        parsed = self.parser.parse("open chrome")
        self.assertEqual(parsed.intent, "open_app")
        self.assertEqual(parsed.entities.get("app_name"), "chrome")
        self.assertNotIn("profile", parsed.entities)

    def test_parse_profile_with_numbers(self) -> None:
        """Profile names that include numbers should be captured."""
        parsed = self.parser.parse("open chrome with profile profile 2")
        self.assertEqual(parsed.intent, "open_app")
        self.assertEqual(parsed.entities.get("app_name"), "chrome")
        self.assertEqual(parsed.entities.get("profile"), "profile 2")


if __name__ == "__main__":
    unittest.main()