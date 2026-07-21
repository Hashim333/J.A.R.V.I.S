"""Tests for the interactive launching system.

These tests verify that:
  1. OCR is functional and can read screen text
  2. UI element detection works
  3. Chrome profile picker detection works
  4. Window detection works
"""

import unittest
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from automation.ui_detector import (
    get_screen_text, find_text_on_screen, find_profile_cards,
    detect_window_by_title, get_active_window_region,
    UIElement,
)
from automation.interactive_launcher import (
    _find_profile_by_name, _speak_choices, _ask_choice,
    _extract_dialog_options,
)


class TestUIDetector(unittest.TestCase):
    """Tests for the UI detection layer."""

    def test_get_screen_text_returns_string(self):
        """get_screen_text should return a non-empty string."""
        text = get_screen_text()
        self.assertIsInstance(text, str)
        self.assertGreater(len(text), 0)

    def test_find_text_on_screen_returns_list(self):
        """find_text_on_screen should return a list of UIElement."""
        elements = find_text_on_screen("chrome", threshold=0.3)
        self.assertIsInstance(elements, list)
        for el in elements:
            self.assertIsInstance(el, UIElement)
            self.assertGreater(el.width, 0)
            self.assertGreater(el.height, 0)

    def test_find_profile_cards_returns_list(self):
        """find_profile_cards should return a list (may be empty)."""
        profiles = find_profile_cards()
        self.assertIsInstance(profiles, list)

    def test_detect_window_by_title_returns_dict_or_none(self):
        """detect_window_by_title should return a dict or None."""
        result = detect_window_by_title("Chrome")
        if result is not None:
            self.assertIn("title", result)
            self.assertIn("left", result)
            self.assertIn("top", result)
            self.assertIn("width", result)
            self.assertIn("height", result)

    def test_get_active_window_region_returns_tuple_or_none(self):
        """get_active_window_region should return a tuple or None."""
        region = get_active_window_region()
        if region is not None:
            self.assertEqual(len(region), 4)
            x, y, w, h = region
            self.assertGreater(w, 0)
            self.assertGreater(h, 0)


class TestInteractiveLauncher(unittest.TestCase):
    """Tests for the interactive launcher logic."""

    def test_find_profile_by_name_exact(self):
        """Exact name match should return the correct index."""
        names = ["Personal", "Work", "Guest", "Default"]
        self.assertEqual(_find_profile_by_name(names, "Work"), 1)
        self.assertEqual(_find_profile_by_name(names, "Personal"), 0)
        self.assertEqual(_find_profile_by_name(names, "Default"), 3)

    def test_find_profile_by_name_case_insensitive(self):
        """Case-insensitive match should work."""
        names = ["Personal", "Work", "Testing"]
        self.assertEqual(_find_profile_by_name(names, "work"), 1)
        self.assertEqual(_find_profile_by_name(names, "PERSONAL"), 0)

    def test_find_profile_by_name_partial(self):
        """Partial prefix match should work."""
        names = ["Personal", "Work", "Testing"]
        self.assertEqual(_find_profile_by_name(names, "Pers"), 0)
        self.assertEqual(_find_profile_by_name(names, "wor"), 1)

    def test_find_profile_by_name_not_found(self):
        """No match should return None."""
        names = ["Personal", "Work"]
        self.assertIsNone(_find_profile_by_name(names, "Nonexistent"))
        self.assertIsNone(_find_profile_by_name(names, ""))

    def test_find_profile_by_name_empty_list(self):
        """Empty list should return None."""
        self.assertIsNone(_find_profile_by_name([], "test"))

    def test_extract_dialog_options_returns_list(self):
        """_extract_dialog_options should return a list."""
        options = _extract_dialog_options()
        self.assertIsInstance(options, list)

    def test_ui_element_properties(self):
        """UIElement should have correct derived properties."""
        el = UIElement(text="Test", x=100, y=200, width=50, height=30, confidence=0.9)
        self.assertEqual(el.center_x, 125)
        self.assertEqual(el.center_y, 215)
        self.assertEqual(el.center, (125, 215))

    def test_ui_element_zero_size(self):
        """UIElement with zero size should still have valid center."""
        el = UIElement(text="Test", x=100, y=200, width=0, height=0, confidence=0.9)
        self.assertEqual(el.center_x, 100)
        self.assertEqual(el.center_y, 200)


if __name__ == "__main__":
    unittest.main()
