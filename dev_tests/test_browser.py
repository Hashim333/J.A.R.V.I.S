"""
dev_tests/test_browser.py

Unit tests for the context-aware browser automation module.
"""

import unittest
from unittest.mock import patch, MagicMock

from automation.browser import (
    search,
    open_url,
    BrowserOperationError,
    new_tab,
    close_current_tab,
    close_all_tabs,
    next_tab,
    previous_tab,
    duplicate_tab,
    reopen_closed_tab,
    refresh_page,
)


class TestBrowserAutomation(unittest.TestCase):
    """Tests for browser automation functions."""

    def setUp(self):
        self._is_site_open_patcher = patch("automation.browser._is_site_open")
        self._focus_chrome_patcher = patch("automation.browser._focus_chrome")
        self._navigate_patcher = patch("automation.browser._navigate_current_tab")
        self._search_shortcut_patcher = patch("automation.browser._search_via_shortcut")
        self._wait_patcher = patch("automation.browser._wait_after_nav")

        self.mock_is_site_open = self._is_site_open_patcher.start()
        self.mock_focus_chrome = self._focus_chrome_patcher.start()
        self.mock_navigate = self._navigate_patcher.start()
        self.mock_search_shortcut = self._search_shortcut_patcher.start()
        self.mock_wait = self._wait_patcher.start()

        self.addCleanup(self._is_site_open_patcher.stop)
        self.addCleanup(self._focus_chrome_patcher.stop)
        self.addCleanup(self._navigate_patcher.stop)
        self.addCleanup(self._search_shortcut_patcher.stop)
        self.addCleanup(self._wait_patcher.stop)

    # -- open_url tests --------------------------------------------------------

    def test_open_url_known_site_not_open_opens_new_tab(self) -> None:
        """Known site that isn't open should navigate a new tab."""
        self.mock_is_site_open.return_value = False
        open_url("youtube")
        self.mock_focus_chrome.assert_called_once()
        self.mock_navigate.assert_called_once_with("https://www.youtube.com")

    def test_open_url_known_site_already_open_focuses(self) -> None:
        """Known site that IS open should only focus Chrome."""
        self.mock_is_site_open.return_value = True
        open_url("youtube")
        self.mock_focus_chrome.assert_called_once_with("youtube")
        self.mock_navigate.assert_not_called()

    def test_open_url_full_url_not_open_opens_new_tab(self) -> None:
        self.mock_is_site_open.return_value = False
        open_url("https://www.python.org")
        self.mock_focus_chrome.assert_called_once()
        self.mock_navigate.assert_called_once_with("https://www.python.org")

    def test_open_url_unknown_site_with_dot(self) -> None:
        self.mock_is_site_open.return_value = False
        open_url("example.com")
        self.mock_navigate.assert_called_once_with("https://example.com")

    def test_open_url_empty_raises_error(self) -> None:
        with self.assertRaises(BrowserOperationError):
            open_url("")

    def test_open_url_unknown_site_no_dot_raises_error(self) -> None:
        with self.assertRaises(BrowserOperationError):
            open_url("notasite")

    # -- search tests ----------------------------------------------------------

    def test_search_google_not_open(self) -> None:
        self.mock_is_site_open.return_value = False
        search("google", "python decorators")
        self.mock_navigate.assert_called_once_with(
            "https://www.google.com/search?q=python+decorators"
        )

    def test_search_google_already_open(self) -> None:
        self.mock_is_site_open.return_value = True
        search("google", "python decorators")
        self.mock_focus_chrome.assert_called_once_with("google")
        self.mock_navigate.assert_called_once_with(
            "https://www.google.com/search?q=python+decorators"
        )

    def test_search_youtube_not_open(self) -> None:
        self.mock_is_site_open.return_value = False
        search("youtube", "lo fi hip hop")
        self.mock_navigate.assert_called_once_with(
            "https://www.youtube.com/results?search_query=lo+fi+hip+hop"
        )

    def test_search_youtube_already_open_uses_shortcut(self) -> None:
        """YouTube has a keyboard shortcut — should use it when already open."""
        self.mock_is_site_open.return_value = True
        search("youtube", "lo fi hip hop")
        self.mock_focus_chrome.assert_called_once_with("youtube")
        self.mock_search_shortcut.assert_called_once_with("youtube", "lo fi hip hop")
        self.mock_navigate.assert_not_called()

    def test_search_github_not_open(self) -> None:
        self.mock_is_site_open.return_value = False
        search("github", "openai")
        self.mock_navigate.assert_called_once_with(
            "https://github.com/search?q=openai"
        )

    def test_search_github_already_open_uses_shortcut(self) -> None:
        self.mock_is_site_open.return_value = True
        search("github", "openai")
        self.mock_focus_chrome.assert_called_once_with("github")
        self.mock_search_shortcut.assert_called_once_with("github", "openai")
        self.mock_navigate.assert_not_called()

    def test_search_wikipedia_not_open(self) -> None:
        self.mock_is_site_open.return_value = False
        search("wikipedia", "kerala")
        self.mock_navigate.assert_called_once_with(
            "https://en.wikipedia.org/w/index.php?search=kerala"
        )

    def test_search_stackoverflow_not_open(self) -> None:
        self.mock_is_site_open.return_value = False
        search("stackoverflow", "selenium python")
        self.mock_navigate.assert_called_once_with(
            "https://stackoverflow.com/search?q=selenium+python"
        )

    def test_search_facebook_not_open(self) -> None:
        self.mock_is_site_open.return_value = False
        search("facebook", "openai")
        self.mock_navigate.assert_called_once_with(
            "https://www.facebook.com/search/top/?q=openai"
        )

    def test_search_facebook_already_open(self) -> None:
        self.mock_is_site_open.return_value = True
        search("facebook", "openai")
        self.mock_focus_chrome.assert_called_once_with("facebook")
        self.mock_navigate.assert_called_once_with(
            "https://www.facebook.com/search/top/?q=openai"
        )

    def test_search_unsupported_provider_raises_error(self) -> None:
        with self.assertRaises(BrowserOperationError):
            search("bing", "test")

    def test_search_empty_query_raises_error(self) -> None:
        with self.assertRaises(BrowserOperationError):
            search("google", "  ")

    # -- Tab management tests --------------------------------------------------

    @patch("automation.browser.pyautogui")
    @patch("automation.browser.windows.focus_window")
    @patch("automation.browser.apps.is_running")
    def test_new_tab(
        self,
        mock_is_running: MagicMock,
        mock_focus: MagicMock,
        mock_pyautogui: MagicMock,
    ) -> None:
        mock_is_running.return_value = True
        mock_focus.return_value = True
        new_tab()
        mock_pyautogui.hotkey.assert_called_once_with("ctrl", "t")

    @patch("automation.browser.pyautogui")
    @patch("automation.browser.windows.focus_window")
    @patch("automation.browser.apps.is_running")
    def test_close_current_tab(
        self,
        mock_is_running: MagicMock,
        mock_focus: MagicMock,
        mock_pyautogui: MagicMock,
    ) -> None:
        mock_is_running.return_value = True
        mock_focus.return_value = True
        close_current_tab()
        mock_pyautogui.hotkey.assert_called_once_with("ctrl", "w")

    @patch("automation.browser.pyautogui")
    @patch("automation.browser.windows.focus_window")
    @patch("automation.browser.apps.is_running")
    def test_close_all_tabs(
        self,
        mock_is_running: MagicMock,
        mock_focus: MagicMock,
        mock_pyautogui: MagicMock,
    ) -> None:
        mock_is_running.return_value = True
        mock_focus.return_value = True
        close_all_tabs()
        mock_pyautogui.hotkey.assert_called_once_with("ctrl", "shift", "w")

    @patch("automation.browser.pyautogui")
    @patch("automation.browser.windows.focus_window")
    @patch("automation.browser.apps.is_running")
    def test_next_tab(
        self,
        mock_is_running: MagicMock,
        mock_focus: MagicMock,
        mock_pyautogui: MagicMock,
    ) -> None:
        mock_is_running.return_value = True
        mock_focus.return_value = True
        next_tab()
        mock_pyautogui.hotkey.assert_called_once_with("ctrl", "tab")

    @patch("automation.browser.pyautogui")
    @patch("automation.browser.windows.focus_window")
    @patch("automation.browser.apps.is_running")
    def test_previous_tab(
        self,
        mock_is_running: MagicMock,
        mock_focus: MagicMock,
        mock_pyautogui: MagicMock,
    ) -> None:
        mock_is_running.return_value = True
        mock_focus.return_value = True
        previous_tab()
        mock_pyautogui.hotkey.assert_called_once_with("ctrl", "shift", "tab")

    @patch("automation.browser.pyautogui")
    @patch("automation.browser.windows.focus_window")
    @patch("automation.browser.apps.is_running")
    def test_duplicate_tab(
        self,
        mock_is_running: MagicMock,
        mock_focus: MagicMock,
        mock_pyautogui: MagicMock,
    ) -> None:
        mock_is_running.return_value = True
        mock_focus.return_value = True
        duplicate_tab()
        mock_pyautogui.hotkey.assert_any_call("alt", "d")
        mock_pyautogui.hotkey.assert_any_call("alt", "enter")

    @patch("automation.browser.pyautogui")
    @patch("automation.browser.windows.focus_window")
    @patch("automation.browser.apps.is_running")
    def test_reopen_closed_tab(
        self,
        mock_is_running: MagicMock,
        mock_focus: MagicMock,
        mock_pyautogui: MagicMock,
    ) -> None:
        mock_is_running.return_value = True
        mock_focus.return_value = True
        reopen_closed_tab()
        mock_pyautogui.hotkey.assert_called_once_with("ctrl", "shift", "t")

    @patch("automation.browser.pyautogui")
    @patch("automation.browser.windows.focus_window")
    @patch("automation.browser.apps.is_running")
    def test_refresh_page(
        self,
        mock_is_running: MagicMock,
        mock_focus: MagicMock,
        mock_pyautogui: MagicMock,
    ) -> None:
        mock_is_running.return_value = True
        mock_focus.return_value = True
        refresh_page()
        mock_pyautogui.press.assert_called_once_with("f5")

    @patch("automation.browser.pyautogui")
    @patch("automation.browser.windows.focus_window")
    @patch("automation.browser.apps.is_running")
    def test_hard_refresh_page(
        self,
        mock_is_running: MagicMock,
        mock_focus: MagicMock,
        mock_pyautogui: MagicMock,
    ) -> None:
        mock_is_running.return_value = True
        mock_focus.return_value = True
        refresh_page(hard=True)
        mock_pyautogui.hotkey.assert_called_once_with("ctrl", "shift", "r")


if __name__ == "__main__":
    unittest.main()
