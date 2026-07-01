"""
dev_tests/test_browser.py

Unit tests for the browser automation module.
"""

import unittest
from unittest.mock import patch, call

from automation.browser import search, open_url, BrowserOperationError, new_tab, close_current_tab, close_all_tabs, next_tab, previous_tab, duplicate_tab, reopen_closed_tab, refresh_page


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
    
    @patch("automation.browser.pyautogui")
    def test_new_tab(self, mock_pyautogui: unittest.mock.MagicMock) -> None:
        """Verify new_tab sends Ctrl+T."""
        new_tab()
        mock_pyautogui.hotkey.assert_called_once_with("ctrl", "t")

    @patch("automation.browser.pyautogui")
    def test_close_current_tab(self, mock_pyautogui: unittest.mock.MagicMock) -> None:
        """Verify close_current_tab sends Ctrl+W."""
        close_current_tab()
        mock_pyautogui.hotkey.assert_called_once_with("ctrl", "w")

    @patch("automation.browser.pyautogui")
    def test_close_all_tabs(self, mock_pyautogui: unittest.mock.MagicMock) -> None:
        """Verify close_all_tabs sends Ctrl+Shift+W."""
        close_all_tabs()
        mock_pyautogui.hotkey.assert_called_once_with("ctrl", "shift", "w")

    @patch("automation.browser.pyautogui")
    def test_next_tab(self, mock_pyautogui: unittest.mock.MagicMock) -> None:
        """Verify next_tab sends Ctrl+Tab."""
        next_tab()
        mock_pyautogui.hotkey.assert_called_once_with("ctrl", "tab")

    @patch("automation.browser.pyautogui")
    def test_previous_tab(self, mock_pyautogui: unittest.mock.MagicMock) -> None:
        """Verify previous_tab sends Ctrl+Shift+Tab."""
        previous_tab()
        mock_pyautogui.hotkey.assert_called_once_with("ctrl", "shift", "tab")

    @patch("automation.browser.pyautogui")
    def test_duplicate_tab(self, mock_pyautogui: unittest.mock.MagicMock) -> None:
        """Verify duplicate_tab sends Alt+D, then Alt+Enter."""
        duplicate_tab()
        mock_pyautogui.hotkey.assert_has_calls([
            call("alt", "d"),
            call("alt", "enter"),
        ])

    @patch("automation.browser.pyautogui")
    def test_reopen_closed_tab(self, mock_pyautogui: unittest.mock.MagicMock) -> None:
        """Verify reopen_closed_tab sends Ctrl+Shift+T."""
        reopen_closed_tab()
        mock_pyautogui.hotkey.assert_called_once_with("ctrl", "shift", "t")

    @patch("automation.browser.pyautogui")
    def test_refresh_page(self, mock_pyautogui: unittest.mock.MagicMock) -> None:
        """Verify refresh_page sends F5."""
        refresh_page()
        mock_pyautogui.press.assert_called_once_with("f5")

    @patch("automation.browser.pyautogui")
    def test_hard_refresh_page(self, mock_pyautogui: unittest.mock.MagicMock) -> None:
        """Verify hard refresh sends Ctrl+Shift+R."""
        refresh_page(hard=True)
        mock_pyautogui.hotkey.assert_called_once_with("ctrl", "shift", "r")

    @patch("automation.browser.pyautogui", new_callable=unittest.mock.MagicMock)
    def test_functions_raise_browser_operation_error_on_failure(self, mock_pyautogui: unittest.mock.MagicMock) -> None:
        """Verify automation functions raise BrowserOperationError on exception."""
        mock_pyautogui.hotkey.side_effect = Exception("test error")
        mock_pyautogui.press.side_effect = Exception("test error")

        functions_to_test = [
            new_tab, close_current_tab, close_all_tabs, next_tab, previous_tab,
            duplicate_tab, reopen_closed_tab, refresh_page
        ]
        for func in functions_to_test:
            with self.assertRaises(BrowserOperationError, msg=f"{func.__name__} did not raise"):
                func()

if __name__ == "__main__":
    unittest.main()
