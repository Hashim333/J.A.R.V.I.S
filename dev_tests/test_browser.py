"""
dev_tests/test_browser.py

Unit tests for the CDP/DOM-driven browser automation module.
"""

import unittest
from unittest.mock import MagicMock, patch

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
    current_state,
    selected_text,
    scroll,
)
from automation.cdp import CdpTab


def _tab(tab_id: str = "tab-1", url: str = "https://www.youtube.com",
         title: str = "YouTube", active: bool = True) -> CdpTab:
    return CdpTab(
        tab_id=tab_id, title=title, url=url,
        active=active, window_id=1,
        ws_url=f"ws://127.0.0.1:9222/{tab_id}",
    )


def _fake_client(tabs=None, active=None, page_state=None):
    client = MagicMock()
    tabs = [tabs] if isinstance(tabs, CdpTab) else (tabs or [])
    client.list_tabs.return_value = tabs
    client.active_tab.return_value = active or (tabs[0] if tabs else None)
    client.find_tab.return_value = None
    client.activate.return_value = True
    client.new_tab.return_value = _tab(tab_id="tab-new", url="about:blank")
    client.close_tab.return_value = True
    client.reload.return_value = None
    client.evaluate.return_value = True
    client.page_state.return_value = page_state or {
        "url": "https://www.youtube.com", "title": "YouTube",
        "selectedText": "", "readyState": "complete",
    }
    client.accessibility_tree.return_value = []
    return client


class TestBrowserAutomation(unittest.TestCase):
    """Tests for browser automation functions over CDP."""

    # -- open_url --------------------------------------------------------

    def test_open_url_known_site_reuses_existing_tab(self) -> None:
        """Known site reuses an existing tab on the same domain."""
        fake = _fake_client(tabs=[_tab()])
        fake.find_tab.return_value = _tab()
        with patch("automation.browser._client", return_value=fake):
            result = open_url("youtube")
        self.assertTrue(result["success"])
        self.assertTrue(result["details"]["reused"])
        fake.activate.assert_called_once()
        fake.new_tab.assert_not_called()

    def test_open_url_opens_new_tab_when_none_open(self) -> None:
        fake = _fake_client()
        fake.find_tab.return_value = None
        with patch("automation.browser._client", return_value=fake):
            result = open_url("https://www.python.org")
        self.assertTrue(result["success"])
        self.assertFalse(result["details"]["reused"])
        fake.new_tab.assert_called_once_with("https://www.python.org")

    def test_open_url_known_site_normalizes(self) -> None:
        fake = _fake_client()
        fake.find_tab.return_value = None
        with patch("automation.browser._client", return_value=fake):
            result = open_url("example.com")
        self.assertTrue(result["success"])
        fake.new_tab.assert_called_once_with("https://example.com")

    def test_open_url_empty_raises_error(self) -> None:
        with self.assertRaises(BrowserOperationError):
            open_url("")

    def test_open_url_unknown_site_no_dot_raises_error(self) -> None:
        with self.assertRaises(BrowserOperationError):
            open_url("notasite")

    # -- search ----------------------------------------------------------

    def test_search_google_opens_new_tab(self) -> None:
        fake = _fake_client()
        fake.find_tab.return_value = None
        with patch("automation.browser._client", return_value=fake):
            result = search("google", "python decorators")
        self.assertTrue(result["success"])
        fake.new_tab.assert_called_once_with(
            "https://www.google.com/search?q=python+decorators"
        )

    def test_search_youtube_reuses_results_tab(self) -> None:
        fake = _fake_client()
        results = _tab(tab_id="results", url="https://www.youtube.com/results")
        fake.find_tab.side_effect = lambda url_substring=None, title_substring=None: (
            results if url_substring == "youtube.com/results" else None
        )
        with patch("automation.browser._client", return_value=fake):
            result = search("youtube", "lo fi hip hop")
        self.assertTrue(result["success"])
        self.assertTrue(result["details"]["reused"])
        fake.navigate.assert_called_once_with(
            results,
            "https://www.youtube.com/results?search_query=lo+fi+hip+hop",
        )
        fake.new_tab.assert_not_called()

    def test_search_youtube_opens_new_tab(self) -> None:
        fake = _fake_client()
        fake.find_tab.return_value = None
        with patch("automation.browser._client", return_value=fake):
            result = search("youtube", "lo fi hip hop")
        self.assertTrue(result["success"])
        fake.new_tab.assert_called_once_with(
            "https://www.youtube.com/results?search_query=lo+fi+hip+hop"
        )

    def test_search_github(self) -> None:
        fake = _fake_client()
        fake.find_tab.return_value = None
        with patch("automation.browser._client", return_value=fake):
            result = search("github", "openai")
        self.assertTrue(result["success"])
        fake.new_tab.assert_called_once_with("https://github.com/search?q=openai")

    def test_search_wikipedia(self) -> None:
        fake = _fake_client()
        fake.find_tab.return_value = None
        with patch("automation.browser._client", return_value=fake):
            result = search("wikipedia", "kerala")
        self.assertTrue(result["success"])
        fake.new_tab.assert_called_once_with(
            "https://en.wikipedia.org/w/index.php?search=kerala"
        )

    def test_search_unsupported_provider_fails(self) -> None:
        with patch("automation.browser._client") as mock_client:
            result = search("bing", "test")
        mock_client.assert_not_called()
        self.assertFalse(result["success"])

    def test_search_empty_query_fails(self) -> None:
        with patch("automation.browser._client") as mock_client:
            result = search("google", "  ")
        mock_client.assert_not_called()
        self.assertFalse(result["success"])

    # -- Tab management --------------------------------------------------

    def test_new_tab(self) -> None:
        fake = _fake_client()
        with patch("automation.browser._client", return_value=fake):
            result = new_tab()
        self.assertTrue(result["success"])
        fake.new_tab.assert_called_once()

    def test_close_current_tab(self) -> None:
        fake = _fake_client(tabs=[_tab()])
        with patch("automation.browser._client", return_value=fake):
            result = close_current_tab()
        self.assertTrue(result["success"])
        fake.close_tab.assert_called_once()

    def test_close_all_tabs(self) -> None:
        fake = _fake_client(tabs=[_tab(tab_id="1"), _tab(tab_id="2")])
        with patch("automation.browser._client", return_value=fake):
            result = close_all_tabs()
        self.assertTrue(result["success"])
        self.assertEqual(fake.close_tab.call_count, 2)

    def test_next_tab(self) -> None:
        fake = _fake_client(tabs=[_tab(tab_id="1"), _tab(tab_id="2", active=False)])
        with patch("automation.browser._client", return_value=fake):
            result = next_tab()
        self.assertTrue(result["success"])

    def test_previous_tab(self) -> None:
        fake = _fake_client(tabs=[_tab(tab_id="1"), _tab(tab_id="2", active=False)])
        with patch("automation.browser._client", return_value=fake):
            result = previous_tab()
        self.assertTrue(result["success"])

    def test_duplicate_tab(self) -> None:
        fake = _fake_client(tabs=[_tab()])
        with patch("automation.browser._client", return_value=fake):
            result = duplicate_tab()
        self.assertTrue(result["success"])
        fake.new_tab.assert_called_once_with("https://www.youtube.com")

    def test_reopen_closed_tab_is_honest(self) -> None:
        result = reopen_closed_tab()
        self.assertFalse(result["success"])

    def test_refresh_page(self) -> None:
        fake = _fake_client(tabs=[_tab()])
        with patch("automation.browser._client", return_value=fake):
            result = refresh_page()
        self.assertTrue(result["success"])
        fake.reload.assert_called_once()

    def test_hard_refresh_page(self) -> None:
        fake = _fake_client(tabs=[_tab()])
        with patch("automation.browser._client", return_value=fake):
            result = refresh_page(hard=True)
        self.assertTrue(result["success"])
        fake.reload.assert_called_once_with(fake.active_tab.return_value, ignore_cache=True)

    # -- Page reading ----------------------------------------------------

    def test_current_state_returns_page_details(self) -> None:
        fake = _fake_client(tabs=[_tab()], page_state={
            "url": "https://www.youtube.com/watch?v=abc",
            "title": "Video - YouTube",
            "selectedText": "selected words",
            "readyState": "complete",
        })
        with patch("automation.browser._client", return_value=fake):
            result = current_state()
        self.assertTrue(result["success"])
        self.assertEqual(result["details"]["url"], "https://www.youtube.com/watch?v=abc")
        self.assertEqual(result["details"]["selected_text"], "selected words")

    def test_selected_text(self) -> None:
        fake = _fake_client(tabs=[_tab()], page_state={
            "url": "x", "title": "y", "selectedText": "hello", "readyState": "complete",
        })
        with patch("automation.browser._client", return_value=fake):
            self.assertEqual(selected_text(), "hello")

    def test_scroll_returns_success(self) -> None:
        fake = _fake_client(tabs=[_tab()])
        with patch("automation.browser._client", return_value=fake):
            result = scroll("down")
        self.assertTrue(result["success"])
        self.assertEqual(result["details"]["direction"], "down")


# ===========================================================================
# No-OCR / no-coordinates guarantees
# ===========================================================================

class TestNoScreenAutomation(unittest.TestCase):
    """The browser layer must never touch pyautogui, pygetwindow or OCR."""

    def test_browser_module_has_no_pyautogui(self) -> None:
        import automation.browser as browser
        self.assertFalse(hasattr(browser, "pyautogui"))
        self.assertFalse(hasattr(browser, "pygetwindow"))
        self.assertFalse(hasattr(browser, "gw"))
        self.assertFalse(hasattr(browser, "ui_detector"))

    def test_browser_module_has_no_ui_detector_import(self) -> None:
        import automation.browser as browser
        source = open(browser.__file__, encoding="utf-8").read()
        self.assertNotIn("ui_detector", source)
        self.assertNotIn("pyautogui", source)
        self.assertNotIn("pygetwindow", source)


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
