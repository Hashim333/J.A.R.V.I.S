import unittest
from unittest.mock import MagicMock, patch

from context_manager.clarification_engine import (
    ClarificationEngine,
    ClarificationState,
    ClarificationType,
)
from context_manager.context_manager import ContextManager
from models.response import Response


class TestClarificationEngine(unittest.TestCase):
    def setUp(self):
        self.engine = ClarificationEngine()

    def test_no_pending_initially(self):
        self.assertFalse(self.engine.has_pending)

    def test_set_pending_and_resolve_app_running_switch(self):
        self.engine.set_pending(
            question="Chrome is already running. Switch?",
            ctype=ClarificationType.APP_ALREADY_RUNNING,
            context={"app_name": "chrome"},
        )
        self.assertTrue(self.engine.has_pending)
        self.assertEqual("Chrome is already running. Switch?", self.engine.pending_question)

        result = self.engine.resolve_answer("switch to it")
        self.assertEqual(result["action"], "switch_to_existing")
        self.assertEqual(result["intent"], "focus_app")
        self.assertFalse(self.engine.has_pending)

    def test_set_pending_and_resolve_app_running_new(self):
        self.engine.set_pending(
            question="Chrome is already running. Switch?",
            ctype=ClarificationType.APP_ALREADY_RUNNING,
            context={"app_name": "chrome"},
        )
        result = self.engine.resolve_answer("open another")
        self.assertEqual(result["action"], "open_new_window")
        self.assertEqual(result["intent"], "open_app")
        self.assertFalse(self.engine.has_pending)

    def test_tab_already_open_switch(self):
        self.engine.set_pending(
            question="YouTube tab exists. Switch?",
            ctype=ClarificationType.TAB_ALREADY_OPEN,
            context={"website": "youtube"},
        )
        result = self.engine.resolve_answer("switch to it")
        self.assertEqual(result["action"], "switch_to_tab")
        self.assertEqual(result["intent"], "focus_tab")

    def test_tab_already_open_new_tab(self):
        self.engine.set_pending(
            question="YouTube tab exists. New tab?",
            ctype=ClarificationType.TAB_ALREADY_OPEN,
            context={"website": "youtube"},
        )
        result = self.engine.resolve_answer("new tab")
        self.assertEqual(result["action"], "open_new_tab")
        self.assertEqual(result["intent"], "open_website")

    def test_search_current_or_new_current(self):
        self.engine.set_pending(
            question="Search in current or new tab?",
            ctype=ClarificationType.CURRENT_OR_NEW_TAB,
            context={"query": "python", "provider": "google"},
        )
        result = self.engine.resolve_answer("current tab")
        self.assertEqual(result["action"], "use_current_tab")
        self.assertEqual(result["intent"], "search")

    def test_search_current_or_new_new(self):
        self.engine.set_pending(
            question="Search in current or new tab?",
            ctype=ClarificationType.CURRENT_OR_NEW_TAB,
            context={"query": "python", "provider": "google"},
        )
        result = self.engine.resolve_answer("new tab")
        self.assertEqual(result["action"], "open_new_tab")
        self.assertEqual(result["intent"], "search")

    def test_unknown_answer_returns_unknown_action(self):
        self.engine.set_pending(
            question="Chrome is running. Switch?",
            ctype=ClarificationType.APP_ALREADY_RUNNING,
            context={"app_name": "chrome"},
        )
        result = self.engine.resolve_answer("maybe later")
        self.assertEqual(result["action"], "unknown")

    def test_resolve_without_pending_returns_unknown(self):
        result = self.engine.resolve_answer("yes")
        self.assertEqual(result["action"], "none")

    def test_clear_pending(self):
        self.engine.set_pending(
            question="Test question?",
            ctype=ClarificationType.APP_ALREADY_RUNNING,
        )
        self.assertTrue(self.engine.has_pending)
        self.engine.clear_pending()
        self.assertFalse(self.engine.has_pending)

    def test_store_last_command(self):
        self.engine.store_last_command("open Chrome")
        self.assertEqual(self.engine.get_last_command(), "open Chrome")


class TestContextManagerAppCheck(unittest.TestCase):
    def setUp(self):
        self.cm = ContextManager()

    @patch("context_manager.app_detector.AppDetector.detect")
    def test_app_not_running_returns_none(self, mock_detect):
        mock_detect.return_value.running = False
        mock_detect.return_value.windows = []

        result = self.cm.check_before_execution(
            "open_app",
            {"app_name": "chrome", "original_app": "chrome"},
            "open Chrome",
        )
        self.assertIsNone(result)

    @patch("context_manager.app_detector.AppDetector.detect")
    def test_app_running_and_focused_returns_success(self, mock_detect):
        from context_manager.app_detector import WindowState
        mock_detect.return_value.running = True
        mock_detect.return_value.windows = [
            WindowState(hwnd=1, title="Chrome", pid=100, is_minimized=False,
                        is_maximized=True, is_focused=True, is_visible=True),
        ]

        result = self.cm.check_before_execution(
            "open_app",
            {"app_name": "chrome", "original_app": "Chrome"},
            "open Chrome",
        )
        self.assertIsNotNone(result)
        self.assertTrue(result.success)
        self.assertIn("focused", result.message)

    @patch("context_manager.app_detector.AppDetector.detect")
    def test_app_running_not_focused_asks_switch_or_new(self, mock_detect):
        from context_manager.app_detector import WindowState
        mock_detect.return_value.running = True
        mock_detect.return_value.windows = [
            WindowState(hwnd=2, title="Chrome", pid=101, is_minimized=False,
                        is_maximized=True, is_focused=False, is_visible=True),
        ]

        result = self.cm.check_before_execution(
            "open_app",
            {"app_name": "chrome", "original_app": "Chrome"},
            "open Chrome",
        )
        self.assertIsNotNone(result)
        self.assertFalse(result.success)
        self.assertTrue(result.needs_clarification)
        self.assertIn("already running", result.clarification_question)
        self.assertTrue(self.cm.clarification.has_pending)

    def test_non_app_intent_returns_none(self):
        result = self.cm.check_before_execution(
            "set_volume",
            {"level": 50},
            "set volume to 50",
        )
        self.assertIsNone(result)

    def test_handle_follow_up_switch_to_existing(self):
        self.cm.clarification.set_pending(
            question="Chrome is running. Switch?",
            ctype=ClarificationType.APP_ALREADY_RUNNING,
            context={"app_name": "chrome", "display_name": "Chrome"},
        )
        result = self.cm.handle_follow_up("switch to it")
        self.assertIsNotNone(result)
        self.assertTrue(result.success)
        self.assertEqual(result.data.get("action"), "switch_to_existing")
        self.assertEqual(result.data.get("intent"), "focus_app")

    def test_handle_follow_up_no_pending(self):
        result = self.cm.handle_follow_up("yes")
        self.assertIsNone(result)


class TestContextManagerBrowserCheck(unittest.TestCase):
    def setUp(self):
        self.cm = ContextManager()

    @patch("context_manager.browser_detector.BrowserDetector.find_tab_by_url")
    @patch("context_manager.browser_detector.BrowserDetector.find_tab_by_title")
    def test_website_not_open_returns_none(self, mock_title, mock_url):
        mock_url.return_value = None
        mock_title.return_value = None

        result = self.cm.check_before_execution(
            "open_website",
            {"website": "youtube", "url": "https://www.youtube.com"},
            "open YouTube",
        )
        self.assertIsNone(result)

    @patch("context_manager.browser_detector.BrowserDetector.find_tab_by_url")
    @patch("context_manager.browser_detector.BrowserDetector.find_tab_by_title")
    def test_website_already_active(self, mock_title, mock_url):
        from context_manager.browser_detector import BrowserTab
        tab = BrowserTab(id=1, title="YouTube", url="https://www.youtube.com",
                        active=True, window_id=1)
        mock_url.return_value = tab
        mock_title.return_value = None

        result = self.cm.check_before_execution(
            "open_website",
            {"website": "youtube", "url": "https://www.youtube.com"},
            "open YouTube",
        )
        self.assertIsNotNone(result)
        self.assertTrue(result.success)
        self.assertIn("already have", result.message)

    @patch("context_manager.browser_detector.BrowserDetector.find_tab_by_url")
    @patch("context_manager.browser_detector.BrowserDetector.find_tab_by_title")
    def test_website_exists_not_active_asks(self, mock_title, mock_url):
        from context_manager.browser_detector import BrowserTab
        tab = BrowserTab(id=2, title="YouTube - Home", url="https://www.youtube.com",
                        active=False, window_id=1)
        mock_url.return_value = tab
        mock_title.return_value = None

        result = self.cm.check_before_execution(
            "open_website",
            {"website": "youtube", "url": "https://www.youtube.com"},
            "open YouTube",
        )
        self.assertIsNotNone(result)
        self.assertTrue(result.needs_clarification)
        self.assertIn("existing youtube tab", result.clarification_question)

    @patch("context_manager.browser_detector.BrowserDetector.find_tab_by_url")
    def test_search_no_existing_tab_returns_none(self, mock_url):
        mock_url.return_value = None

        result = self.cm.check_before_execution(
            "search",
            {"query": "python tutorial", "provider": "google"},
            "search python tutorial",
        )
        self.assertIsNone(result)

    @patch("context_manager.browser_detector.BrowserDetector.find_tab_by_url")
    def test_search_existing_tab_asks_current_or_new(self, mock_url):
        from context_manager.browser_detector import BrowserTab
        tab = BrowserTab(id=3, title="Google", url="https://www.google.com",
                        active=False, window_id=1)
        mock_url.return_value = tab

        result = self.cm.check_before_execution(
            "search",
            {"query": "python", "provider": "google"},
            "search python",
        )
        self.assertIsNotNone(result)
        self.assertTrue(result.needs_clarification)
        self.assertIn("current", result.clarification_question)


class TestContextManagerFullScenario(unittest.TestCase):
    def setUp(self):
        self.cm = ContextManager()

    def test_full_scenario_open_chrome_twice(self):
        """Simulate: open Chrome -> open Chrome again -> switch"""
        with patch("context_manager.app_detector.AppDetector.detect") as mock_detect:
            from context_manager.app_detector import AppStatus, WindowState

            mock_detect.return_value = AppStatus(
                process_name="chrome.exe",
                display_name="Chrome",
                running=True,
                windows=[
                    WindowState(hwnd=1, title="Chrome", pid=100,
                                is_minimized=False, is_maximized=True,
                                is_focused=False, is_visible=True),
                ],
            )

            r1 = self.cm.check_before_execution(
                "open_app",
                {"app_name": "chrome", "original_app": "Chrome"},
                "open Chrome",
            )
            self.assertIsNotNone(r1)
            self.assertTrue(r1.needs_clarification)
            self.assertIn("already running", r1.clarification_question)
            self.assertTrue(self.cm.has_pending_question())

            r2 = self.cm.handle_follow_up("switch to it")
            self.assertIsNotNone(r2)
            self.assertTrue(r2.success)
            self.assertEqual(r2.data["action"], "switch_to_existing")
            self.assertEqual(r2.data["intent"], "focus_app")
            self.assertFalse(self.cm.has_pending_question())


if __name__ == "__main__":
    unittest.main()
