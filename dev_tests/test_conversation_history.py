"""
Test the conversation history rolling list on the bridge.
Ensures append works, 50-entry cap is enforced, and speaker/text/timestamp
are present on every entry.
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.normpath(os.path.join(os.path.dirname(__file__), "..")))

from PySide6.QtCore import QCoreApplication


class TestConversationHistory(unittest.TestCase):
    """Verify the rolling-list conversation history on the bridge."""

    @classmethod
    def setUpClass(cls):
        if QCoreApplication.instance() is None:
            cls._app = QCoreApplication(sys.argv)
        else:
            cls._app = QCoreApplication.instance()

    def setUp(self):
        from ui.bridge import Bridge
        self.bridge = Bridge()

    def tearDown(self):
        if self.bridge:
            self.bridge._clock_timer.stop()
            self.bridge._stats_timer.stop()
            self.bridge.deleteLater()
        self.bridge = None

    def test_empty_initially(self):
        self.assertEqual(self.bridge.conversationHistory, [])

    def test_add_entry_creates_entry(self):
        self.bridge.add_conversation_entry("USER", "hello")
        self.assertEqual(len(self.bridge.conversationHistory), 1)
        entry = self.bridge.conversationHistory[0]
        self.assertEqual(entry["speaker"], "USER")
        self.assertEqual(entry["text"], "hello")
        self.assertIn("timestamp", entry)
        self.assertRegex(entry["timestamp"], r"\d{2}:\d{2}:\d{2}")

    def test_add_entry_multiple_speakers(self):
        self.bridge.add_conversation_entry("USER", "open chrome")
        self.bridge.add_conversation_entry("JARVIS", "Opening Chrome")
        self.assertEqual(len(self.bridge.conversationHistory), 2)
        self.assertEqual(self.bridge.conversationHistory[0]["speaker"], "USER")
        self.assertEqual(self.bridge.conversationHistory[1]["speaker"], "JARVIS")

    def test_show_subtitle_adds_jarvis_entry(self):
        self.bridge.show_subtitle("I am ready")
        self.assertEqual(len(self.bridge.conversationHistory), 1)
        self.assertEqual(self.bridge.conversationHistory[0]["speaker"], "JARVIS")
        self.assertEqual(self.bridge.conversationHistory[0]["text"], "I am ready")

    def test_empty_text_skipped(self):
        self.bridge.add_conversation_entry("USER", "")
        self.assertEqual(self.bridge.conversationHistory, [])
        self.bridge.add_conversation_entry("JARVIS", "")
        self.assertEqual(self.bridge.conversationHistory, [])

    def test_caps_at_fifty(self):
        for i in range(60):
            self.bridge.add_conversation_entry("USER", f"msg_{i}")
        self.assertEqual(len(self.bridge.conversationHistory), 50)
        first = self.bridge.conversationHistory[0]
        last = self.bridge.conversationHistory[-1]
        self.assertEqual(first["text"], "msg_10")
        self.assertEqual(last["text"], "msg_59")

    def test_signal_emitted_on_new_entry(self):
        self._signal_fired = False
        def spy():
            self._signal_fired = True
        self.bridge.conversationHistoryChanged.connect(spy)
        self.bridge.add_conversation_entry("JARVIS", "hello")
        self.assertTrue(self._signal_fired)

    def test_conversation_history_property_type(self):
        hist = self.bridge.conversationHistory
        self.assertIsInstance(hist, list)

    def test_entry_structure(self):
        self.bridge.add_conversation_entry("JARVIS", "test message")
        entry = self.bridge.conversationHistory[0]
        for key in ("speaker", "text", "timestamp"):
            self.assertIn(key, entry, f"Entry missing key {key}")

    def test_in_place_append(self):
        hist = self.bridge.conversationHistory
        self.bridge.add_conversation_entry("USER", "first")
        hist2 = self.bridge.conversationHistory
        self.assertEqual(len(hist2), 1)
        # The list object is replaced (new copy)
        self.assertIsNot(hist, hist2)


if __name__ == "__main__":
    unittest.main()
