"""
dev_tests/test_browser.py

Unit tests for the browser automation module.
"""

import unittest
from unittest.mock import patch, call

from automation.browser import search, open_url, BrowserOperationError


class TestBrowserAutomation(unittest.TestCase):
    """Tests for browser automation functions."""

    @patch("automation.browser.webbrowser.open")
    def test_search_google(self, mock_open: unittest.mock.MagicMock) -> None:
        """Verify Google search URL construction."""
        search("google", "python decorators")
        mock_open.assert_called_once_with(
            "https://www.google.com/search?q=python+decorators", new=2, autoraise=True
        )

    @patch("automation.browser.webbrowser.open")
    def test_search_youtube(self, mock_open: unittest.mock.MagicMock) -> None:
        """Verify YouTube search URL construction."""
        search("youtube", "lo fi hip hop")
        mock_open.assert_called_once_with(
            "https://www.youtube.com/results?search_query=lo+fi+hip+hop",
            new=2,
            autoraise=True,
        )

    @patch("automation.browser.webbrowser.open")
    def test_search_github(self, mock_open: unittest.mock.MagicMock) -> None:
        """Verify GitHub search URL construction."""
        search("github", "openai")
        mock_open.assert_called_once_with(
            "https://github.com/search?q=openai", new=2, autoraise=True
        )

    @patch("automation.browser.webbrowser.open")
    def test_search_wikipedia(self, mock_open: unittest.mock.MagicMock) -> None:
        """Verify Wikipedia search URL construction."""
        search("wikipedia", "kerala")
        mock_open.assert_called_once_with(
            "https://en.wikipedia.org/w/index.php?search=kerala", new=2, autoraise=True
        )

    @patch("automation.browser.webbrowser.open")
    def test_search_stackoverflow(self, mock_open: unittest.mock.MagicMock) -> None:
        """Verify Stack Overflow search URL construction."""
        search("stackoverflow", "selenium python")
        mock_open.assert_called_once_with(
            "https://stackoverflow.com/search?q=selenium+python", new=2, autoraise=True
        )

    def test_search_unsupported_provider_raises_error(self) -> None:
        """Verify searching with an unknown provider raises an error."""
        with self.assertRaises(BrowserOperationError):
            search("bing", "test")

    def test_search_empty_query_raises_error(self) -> None:
        """Verify that an empty search query raises an error."""
        with self.assertRaises(BrowserOperationError):
            search("google", "  ")

    @patch("automation.browser.webbrowser.open")
    def test_open_url_known_site(self, mock_open: unittest.mock.MagicMock) -> None:
        """Verify opening a known site by its short name."""
        open_url("youtube")
        mock_open.assert_called_once_with(
            "https://www.youtube.com", new=2, autoraise=True
        )

    @patch("automation.browser.webbrowser.open")
    def test_open_url_full_url(self, mock_open: unittest.mock.MagicMock) -> None:
        """Verify opening a full URL as-is."""
        open_url("https://www.python.org")
        mock_open.assert_called_once_with(
            "https://www.python.org", new=2, autoraise=True
        )

if __name__ == "__main__":
    unittest.main()
