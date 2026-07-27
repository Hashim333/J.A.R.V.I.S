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
        self._focus_chrome_patcher = patch("automation.browser._focus_chrome")
        self._navigate_patcher = patch("automation.browser._navigate_current_tab")
        self._new_tab_patcher = patch("automation.browser.new_tab")
        self._search_shortcut_patcher = patch("automation.browser._search_via_shortcut")
        self._wait_patcher = patch("automation.browser._wait_after_nav")

        self.mock_focus_chrome = self._focus_chrome_patcher.start()
        self.mock_navigate = self._navigate_patcher.start()
        self.mock_new_tab = self._new_tab_patcher.start()
        self.mock_search_shortcut = self._search_shortcut_patcher.start()
        self.mock_wait = self._wait_patcher.start()

        self.addCleanup(self._focus_chrome_patcher.stop)
        self.addCleanup(self._navigate_patcher.stop)
        self.addCleanup(self._new_tab_patcher.stop)
        self.addCleanup(self._search_shortcut_patcher.stop)
        self.addCleanup(self._wait_patcher.stop)

    # -- open_url tests --------------------------------------------------------

    def test_open_url_known_site_opens_new_tab(self) -> None:
        """Known site always opens a new tab (safe default)."""
        open_url("youtube")
        self.mock_focus_chrome.assert_called_once()
        self.mock_new_tab.assert_called_once()
        self.mock_navigate.assert_called_once_with("https://www.youtube.com")

    def test_open_url_full_url_opens_new_tab(self) -> None:
        open_url("https://www.python.org")
        self.mock_focus_chrome.assert_called_once()
        self.mock_new_tab.assert_called_once()
        self.mock_navigate.assert_called_once_with("https://www.python.org")

    def test_open_url_unknown_site_with_dot(self) -> None:
        open_url("example.com")
        self.mock_new_tab.assert_called_once()
        self.mock_navigate.assert_called_once_with("https://example.com")

    def test_open_url_empty_raises_error(self) -> None:
        with self.assertRaises(BrowserOperationError):
            open_url("")

    def test_open_url_unknown_site_no_dot_raises_error(self) -> None:
        with self.assertRaises(BrowserOperationError):
            open_url("notasite")

    # -- search tests ----------------------------------------------------------

    def test_search_google(self) -> None:
        search("google", "python decorators")
        self.mock_focus_chrome.assert_called_once()
        self.mock_new_tab.assert_called_once()
        self.mock_navigate.assert_called_once_with(
            "https://www.google.com/search?q=python+decorators"
        )

    def test_search_youtube(self) -> None:
        search("youtube", "lo fi hip hop")
        self.mock_focus_chrome.assert_called_once()
        self.mock_new_tab.assert_called_once()
        self.mock_navigate.assert_called_once_with(
            "https://www.youtube.com/results?search_query=lo+fi+hip+hop"
        )
        self.mock_search_shortcut.assert_called_once_with("youtube", "lo fi hip hop")

    def test_search_github(self) -> None:
        search("github", "openai")
        self.mock_focus_chrome.assert_called_once()
        self.mock_new_tab.assert_called_once()
        self.mock_navigate.assert_called_once_with(
            "https://github.com/search?q=openai"
        )
        self.mock_search_shortcut.assert_called_once_with("github", "openai")

    def test_search_wikipedia(self) -> None:
        search("wikipedia", "kerala")
        self.mock_navigate.assert_called_once_with(
            "https://en.wikipedia.org/w/index.php?search=kerala"
        )

    def test_search_stackoverflow(self) -> None:
        search("stackoverflow", "selenium python")
        self.mock_navigate.assert_called_once_with(
            "https://stackoverflow.com/search?q=selenium+python"
        )

    def test_search_facebook(self) -> None:
        search("facebook", "openai")
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


# ===========================================================================
# Regression tests — BUG 1 / BUG 3 / BUG 5
# ===========================================================================

class TestBrowserSafety(unittest.TestCase):
    """Verify critical safety regressions are fixed."""

    @patch("automation.browser._focus_chrome")
    @patch("automation.browser.new_tab")
    @patch("automation.browser._navigate_current_tab")
    @patch("automation.browser._ensure_safe_focus")
    def test_bug3_open_url_always_new_tab(
        self, mock_safe, mock_nav, mock_new_tab, mock_focus
    ):
        """BUG 3: open_url must always open a new tab before navigating."""
        open_url("https://www.youtube.com")
        mock_focus.assert_called_once()
        mock_new_tab.assert_called_once()
        mock_nav.assert_called_once_with("https://www.youtube.com")

    @patch("automation.browser._focus_chrome")
    @patch("automation.browser.new_tab")
    @patch("automation.browser._navigate_current_tab")
    @patch("automation.browser._search_via_shortcut")
    @patch("automation.browser._wait_after_nav")
    @patch("automation.browser._ensure_safe_focus")
    def test_bug3_search_always_new_tab(
        self, mock_safe, mock_wait, mock_shortcut, mock_nav, mock_new_tab, mock_focus
    ):
        """BUG 3: search must always open a new tab before navigating."""
        search("google", "python")
        mock_focus.assert_called_once()
        mock_new_tab.assert_called_once()
        mock_nav.assert_called_once()

    def test_bug5_verify_foreground_detection(self):
        """BUG 5: _verify_foreground_is should detect chrome in title."""
        from automation.browser import _verify_foreground_is
        with patch("automation.browser.gw.getActiveWindow") as mock_get:
            mock_win = MagicMock()
            mock_win.title = "YouTube - Google Chrome"
            mock_get.return_value = mock_win
            self.assertTrue(_verify_foreground_is("chrome"))

    def test_bug5_verify_foreground_no_match(self):
        """BUG 5: Should return False when foreground is not chrome."""
        from automation.browser import _verify_foreground_is
        with patch("automation.browser.gw.getActiveWindow") as mock_get:
            mock_win = MagicMock()
            mock_win.title = "JARVIS Desktop"
            mock_get.return_value = mock_win
            self.assertFalse(_verify_foreground_is("chrome"))

    @patch("automation.browser.gw.getActiveWindow")
    def test_bug5_verify_none(self, mock_get):
        """BUG 5: Should handle None foreground window."""
        from automation.browser import _verify_foreground_is
        mock_get.return_value = None
        self.assertFalse(_verify_foreground_is("chrome"))


class TestProtectedTabDetection(unittest.TestCase):
    """BUG 1: Protected tabs must never be reused."""

    def setUp(self):
        from context_manager.context_manager import ContextManager
        self.cm = ContextManager()

    def test_chatgpt_is_protected(self):
        self.assertTrue(self.cm._is_protected_tab("https://chatgpt.com", "ChatGPT"))

    def test_gmail_is_protected(self):
        self.assertTrue(self.cm._is_protected_tab("https://mail.google.com", "Gmail"))

    def test_github_is_protected(self):
        self.assertTrue(self.cm._is_protected_tab("https://github.com/user/repo", "GitHub"))

    def test_youtube_is_not_protected(self):
        self.assertFalse(self.cm._is_protected_tab("https://www.youtube.com", "YouTube"))

    def test_google_search_is_not_protected(self):
        self.assertFalse(self.cm._is_protected_tab("https://www.google.com/search?q=cats", "Google Search"))


if __name__ == "__main__":
    unittest.main()
