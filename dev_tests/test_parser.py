"""
dev_tests/test_parser.py

Unit tests for the Parser.
"""

import unittest
from brain.parser import Parser


class TestParserSearch(unittest.TestCase):
    """Tests for browser search parsing."""

    def setUp(self) -> None:
        """Set up the test case."""
        self.parser = Parser()

    def test_search_on_google(self) -> None:
        """Test 'search ... on google' pattern."""
        command = "search python decorators on google"
        parsed = self.parser.parse(command)
        self.assertEqual(parsed.intent, "browser_search")
        self.assertEqual(parsed.entities.get("provider"), "google")
        self.assertEqual(parsed.entities.get("query"), "python decorators")

    def test_search_on_youtube(self) -> None:
        """Test 'search ... on youtube' pattern."""
        command = "search for lofi hip hop on youtube"
        parsed = self.parser.parse(command)
        self.assertEqual(parsed.intent, "browser_search")
        self.assertEqual(parsed.entities.get("provider"), "youtube")
        self.assertEqual(parsed.entities.get("query"), "lofi hip hop")

    def test_search_on_github(self) -> None:
        """Test 'search ... on github' pattern."""
        command = "look up openai on github"
        parsed = self.parser.parse(command)
        self.assertEqual(parsed.intent, "browser_search")
        self.assertEqual(parsed.entities.get("provider"), "github")
        self.assertEqual(parsed.entities.get("query"), "openai")

    def test_search_on_stackoverflow(self) -> None:
        """Test 'search ... on stackoverflow' pattern with alias."""
        command = "search selenium python on stack overflow"
        parsed = self.parser.parse(command)
        self.assertEqual(parsed.intent, "browser_search")
        self.assertEqual(parsed.entities.get("provider"), "stackoverflow")
        self.assertEqual(parsed.entities.get("query"), "selenium python")

    def test_search_on_wikipedia(self) -> None:
        """Test 'search ... on wikipedia' pattern."""
        command = "search kerala on wikipedia"
        parsed = self.parser.parse(command)
        self.assertEqual(parsed.intent, "browser_search")
        self.assertEqual(parsed.entities.get("provider"), "wikipedia")
        self.assertEqual(parsed.entities.get("query"), "kerala")

    def test_provider_first_google(self) -> None:
        """Test '<provider> <query>' pattern for google."""
        command = "google python decorators"
        parsed = self.parser.parse(command)
        self.assertEqual(parsed.intent, "browser_search")
        self.assertEqual(parsed.entities.get("provider"), "google")
        self.assertEqual(parsed.entities.get("query"), "python decorators")

    def test_provider_first_github(self) -> None:
        """Test '<provider> <query>' pattern for github."""
        command = "github openai"
        parsed = self.parser.parse(command)
        self.assertEqual(parsed.intent, "browser_search")
        self.assertEqual(parsed.entities.get("provider"), "github")
        self.assertEqual(parsed.entities.get("query"), "openai")


if __name__ == "__main__":
    unittest.main()
