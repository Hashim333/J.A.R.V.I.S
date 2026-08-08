"""
dev_tests/test_voice_engine.py

Tests for voice/engine.py (VoiceEngine) and enhanced
voice/selection_manager.py (VoiceSelectionManager).

Covers:
  1. VoiceEngine speech queue and threading
  2. VoiceEngine interrupt and cancel_all
  3. VoiceEngine is_speaking property
  4. VoiceSelectionManager smart parsing
  5. VoiceSelectionManager pagination
  6. VoiceSelectionManager short responses
  7. SelectionContext store/clear/expiry
"""

from __future__ import annotations

import threading
import time
import unittest
from unittest.mock import MagicMock, patch

from voice.engine import VoiceEngine
from voice.selection_manager import (
    VoiceSelectionManager,
    SelectionContext,
)
from voice.manager import VoiceManager


# ---------------------------------------------------------------------------
# VoiceEngine Tests
# ---------------------------------------------------------------------------


class TestVoiceEngine(unittest.TestCase):
    def setUp(self) -> None:
        self.mock_manager = MagicMock(spec=VoiceManager)
        self.mock_manager.queue_size = 0
        self.mock_manager.is_playing = False
        self.engine = VoiceEngine(voice_manager=self.mock_manager)

    def test_speak_delegates_to_manager(self) -> None:
        """speak() delegates to VoiceManager.speak()."""
        self.engine.speak("Hello")
        self.mock_manager.speak.assert_called_once_with("Hello", priority=False)

    def test_speak_priority_delegates(self) -> None:
        """speak(priority=True) passes priority to VoiceManager."""
        self.engine.speak("Urgent", priority=True)
        self.mock_manager.speak.assert_called_once_with("Urgent", priority=True)

    def test_speak_empty_text_is_noop(self) -> None:
        """speak() with empty text does not delegate."""
        self.engine.speak("")
        self.engine.speak("   ")
        self.mock_manager.speak.assert_not_called()

    def test_interrupt_delegates_to_manager(self) -> None:
        """interrupt() calls VoiceManager.stop()."""
        self.engine.interrupt()
        self.mock_manager.stop.assert_called_once()

    def test_cancel_all_delegates_to_manager(self) -> None:
        """cancel_all() calls VoiceManager.cancel_all()."""
        self.engine.cancel_all()
        self.mock_manager.cancel_all.assert_called_once()

    def test_is_speaking_from_manager(self) -> None:
        """is_speaking reflects VoiceManager.is_playing."""
        self.assertFalse(self.engine.is_speaking)
        self.mock_manager.is_playing = True
        self.assertTrue(self.engine.is_speaking)

    def test_speak_and_wait_blocks(self) -> None:
        """speak_and_wait() blocks until speech completes."""
        self.mock_manager.queue_size = 0
        self.mock_manager.is_playing = False
        result = self.engine.speak_and_wait("Hello", timeout=2.0)
        self.assertTrue(result)
        self.mock_manager.speak.assert_called_once_with("Hello", priority=False)

    def test_confirm_barge_in_ignores_weak_speech(self) -> None:
        """Barge-in should not interrupt when speech is too short or too quiet."""
        self.engine._barge_in_pending = True
        self.engine._barge_in_started_at = time.monotonic() - 0.2
        self.engine._latest_audio_level = 0.05
        self.engine._voice_manager = self.mock_manager

        self.engine._confirm_barge_in()

        self.mock_manager.stop.assert_not_called()


# ---------------------------------------------------------------------------
# VoiceSelectionManager Smart Parsing Tests
# ---------------------------------------------------------------------------


class TestSmartParsing(unittest.TestCase):
    """Verify that _smart_parse understands natural language selection phrases."""

    def setUp(self) -> None:
        self.manager = VoiceSelectionManager()
        self.options = ["Personal", "Work", "Guest", "Default"]

    def _parse(self, reply: str) -> str | None:
        return self.manager._smart_parse(reply, self.options)

    def test_digit(self) -> None:
        self.assertEqual(self._parse("1"), "Personal")
        self.assertEqual(self._parse("2"), "Work")
        self.assertEqual(self._parse("4"), "Default")

    def test_number_word(self) -> None:
        self.assertEqual(self._parse("one"), "Personal")
        self.assertEqual(self._parse("two"), "Work")
        self.assertEqual(self._parse("four"), "Default")

    def test_ordinal(self) -> None:
        self.assertEqual(self._parse("first"), "Personal")
        self.assertEqual(self._parse("second"), "Work")
        self.assertEqual(self._parse("fourth"), "Default")

    def test_option_prefix_with_digit(self) -> None:
        self.assertEqual(self._parse("option 1"), "Personal")
        self.assertEqual(self._parse("option 3"), "Guest")

    def test_option_prefix_with_word(self) -> None:
        self.assertEqual(self._parse("option one"), "Personal")
        self.assertEqual(self._parse("option two"), "Work")

    def test_number_prefix(self) -> None:
        self.assertEqual(self._parse("number 1"), "Personal")
        self.assertEqual(self._parse("number two"), "Work")

    def test_hash_prefix(self) -> None:
        self.assertEqual(self._parse("#2"), "Work")
        self.assertEqual(self._parse("# 3"), "Guest")

    def test_choose_prefix(self) -> None:
        self.assertEqual(self._parse("choose option two"), "Work")
        self.assertEqual(self._parse("choose option 1"), "Personal")

    def test_pick_prefix(self) -> None:
        self.assertEqual(self._parse("pick option two"), "Work")
        self.assertEqual(self._parse("pick option 1"), "Personal")

    def test_select_prefix(self) -> None:
        self.assertEqual(self._parse("select option three"), "Guest")

    def test_the_one_suffix(self) -> None:
        self.assertEqual(self._parse("the first one"), "Personal")
        self.assertEqual(self._parse("the second one"), "Work")

    def test_the_ordinal(self) -> None:
        self.assertEqual(self._parse("the first"), "Personal")
        self.assertEqual(self._parse("the second"), "Work")

    def test_ordinal_in_phrase(self) -> None:
        self.assertEqual(self._parse("grab the second"), "Work")

    def test_out_of_range_returns_none(self) -> None:
        self.assertIsNone(self._parse("option 10"))
        self.assertIsNone(self._parse("tenth"))

    def test_nonsense_returns_none(self) -> None:
        self.assertIsNone(self._parse("purple monkey dishwasher"))

    def test_case_insensitive(self) -> None:
        self.assertEqual(self._parse("OPTION TWO"), "Work")
        self.assertEqual(self._parse("First"), "Personal")
        self.assertEqual(self._parse("The Second One"), "Work")


# ---------------------------------------------------------------------------
# SelectionContext Tests
# ---------------------------------------------------------------------------


class TestSelectionContext(unittest.TestCase):
    def setUp(self) -> None:
        self.ctx = SelectionContext()

    def test_stores_options(self) -> None:
        self.ctx.store(options=["A", "B", "C"], header="Test")
        self.assertTrue(self.ctx.active)
        self.assertEqual(self.ctx.options, ["A", "B", "C"])
        self.assertEqual(self.ctx.header, "Test")

    def test_clear_resets_state(self) -> None:
        self.ctx.store(options=["A"], header="Test")
        self.ctx.clear()
        self.assertFalse(self.ctx.active)
        self.assertEqual(self.ctx.options, [])

    def test_not_expired_immediately(self) -> None:
        self.ctx.store(options=["A"], header="Test")
        self.assertFalse(self.ctx.is_expired)

    def test_expired_after_timeout(self) -> None:
        self.ctx.store(options=["A"], header="Test", timeout=0.01)
        time.sleep(0.02)
        self.assertTrue(self.ctx.is_expired)

    def test_clear_clears_expiry(self) -> None:
        self.ctx.store(options=["A"], header="Test")
        self.ctx.clear()
        self.assertTrue(self.ctx.is_expired)  # no active -> is_expired


# ---------------------------------------------------------------------------
# VoiceSelectionManager Pagination Tests
# ---------------------------------------------------------------------------


class TestPagination(unittest.TestCase):
    def setUp(self) -> None:
        self.manager = VoiceSelectionManager()
        self.options = [f"File {i}" for i in range(1, 11)]  # 10 options

    def test_next_page(self) -> None:
        manager = VoiceSelectionManager()
        manager._options = self.options
        manager._page = 0
        result = manager._handle_pagination("next", "Files", self.options)
        self.assertEqual(result, "retry")
        self.assertEqual(manager._page, 1)

    def test_previous_page(self) -> None:
        manager = VoiceSelectionManager()
        manager._options = self.options
        manager._page = 1
        result = manager._handle_pagination("previous", "Files", self.options)
        self.assertEqual(result, "retry")
        self.assertEqual(manager._page, 0)

    def test_no_previous_on_first_page(self) -> None:
        manager = VoiceSelectionManager()
        manager._options = self.options
        manager._page = 0
        result = manager._handle_pagination("previous", "Files", self.options)
        self.assertEqual(result, "retry")
        self.assertEqual(manager._page, 0)  # stays on page 0

    def test_no_next_on_last_page(self) -> None:
        manager = VoiceSelectionManager()
        manager._options = self.options
        manager._page = 3  # last page (items 10+)
        result = manager._handle_pagination("next", "Files", self.options)
        self.assertEqual(result, "retry")
        self.assertEqual(manager._page, 3)

    def test_read_all(self) -> None:
        manager = VoiceSelectionManager()
        manager._options = self.options
        with patch.object(manager, "_present_all") as mock:
            result = manager._handle_pagination("read all", "Files", self.options)
        self.assertEqual(result, "retry")
        mock.assert_called_once()

    def test_non_pagination_returns_none(self) -> None:
        """Non-pagination commands should return None (fall through to matching)."""
        result = self.manager._handle_pagination("option two", "Files", self.options)
        self.assertIsNone(result)

    def test_cancel_returns_cancelled(self) -> None:
        """Cancel words should not be handled by pagination."""
        result = self.manager._handle_pagination("cancel", "Files", self.options)
        self.assertIsNone(result)


# ---------------------------------------------------------------------------
# Short Name Formatting Tests
# ---------------------------------------------------------------------------


class TestShortenName(unittest.TestCase):
    def test_strips_extension(self) -> None:
        self.assertEqual(
            VoiceSelectionManager._shorten_name("Resume.pdf"),
            "Resume",
        )
        self.assertEqual(
            VoiceSelectionManager._shorten_name("Document.docx"),
            "Document",
        )

    def test_truncates_long_names(self) -> None:
        long = "A" * 50
        short = VoiceSelectionManager._shorten_name(long, max_chars=30)
        self.assertLessEqual(len(short), 30)

    def test_short_names_unchanged(self) -> None:
        self.assertEqual(
            VoiceSelectionManager._shorten_name("Resume"),
            "Resume",
        )

    def test_truncates_by_word_count(self) -> None:
        many = "word1 word2 word3 word4 word5 word6"
        short = VoiceSelectionManager._shorten_name(many, max_words=3)
        self.assertEqual(short, "word1 word2 word3...")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    unittest.main(verbosity=2)
