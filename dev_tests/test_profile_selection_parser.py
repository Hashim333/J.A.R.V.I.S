"""
dev_tests/test_profile_selection_parser.py

Tests for brain.profile_selection_parser.ProfileSelectionParser
and the intent-based _select_chrome_profile in automation.apps.
"""

from __future__ import annotations

import unittest
from unittest.mock import patch

from brain.profile_selection_parser import ParseResult, ProfileSelectionParser


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

CANDIDATES = ["Muhammed", "Hashi", "amithcs.in"]
ALIASES = {
    "my profile": 0,
    "mine": 0,
    "default": 0,
    "gaming profile": 1,
}


def _parser() -> ProfileSelectionParser:
    return ProfileSelectionParser(candidates=CANDIDATES, aliases=ALIASES)


def _idx(utterance: str) -> int:
    """Return the matched 0-based index, or -1."""
    return _parser().parse(utterance).index


def _conf(utterance: str) -> float:
    return _parser().parse(utterance).confidence


def _low(utterance: str) -> bool:
    return _parser().parse(utterance).low_confidence


# ---------------------------------------------------------------------------
# 1. Numeric / digit selection
# ---------------------------------------------------------------------------

class TestNumericSelection(unittest.TestCase):

    def test_bare_1(self):          self.assertEqual(_idx("1"), 0)
    def test_bare_2(self):          self.assertEqual(_idx("2"), 1)
    def test_bare_3(self):          self.assertEqual(_idx("3"), 2)
    def test_repeated_1_1(self):    self.assertEqual(_idx("1 1"), 0)
    def test_repeated_2_2(self):    self.assertEqual(_idx("2 2"), 1)
    def test_repeated_3_3(self):    self.assertEqual(_idx("3 3"), 2)


# ---------------------------------------------------------------------------
# 2. Spoken number words
# ---------------------------------------------------------------------------

class TestSpokenNumbers(unittest.TestCase):

    def test_one(self):             self.assertEqual(_idx("one"), 0)
    def test_two(self):             self.assertEqual(_idx("two"), 1)
    def test_three(self):           self.assertEqual(_idx("three"), 2)
    def test_one_one(self):         self.assertEqual(_idx("one one"), 0)
    def test_two_two(self):         self.assertEqual(_idx("two two"), 1)
    def test_three_three(self):     self.assertEqual(_idx("three three"), 2)
    def test_mixed_1_one(self):     self.assertEqual(_idx("1 one"), 0)
    def test_mixed_one_1(self):     self.assertEqual(_idx("one 1"), 0)
    def test_mixed_2_two(self):     self.assertEqual(_idx("2 two"), 1)
    def test_mixed_two_2(self):     self.assertEqual(_idx("two 2"), 1)
    def test_mixed_3_three(self):   self.assertEqual(_idx("3 three"), 2)
    def test_mixed_three_3(self):   self.assertEqual(_idx("three 3"), 2)


# ---------------------------------------------------------------------------
# 3. Homophones
# ---------------------------------------------------------------------------

class TestHomophones(unittest.TestCase):

    def test_won(self):             self.assertEqual(_idx("won"), 0)
    def test_too(self):             self.assertEqual(_idx("too"), 1)
    def test_free(self):            self.assertEqual(_idx("free"), 2)
    def test_tree(self):            self.assertEqual(_idx("tree"), 2)


# ---------------------------------------------------------------------------
# 4. Ordinal / positional words
# ---------------------------------------------------------------------------

class TestOrdinals(unittest.TestCase):

    def test_first(self):           self.assertEqual(_idx("first"), 0)
    def test_second(self):          self.assertEqual(_idx("second"), 1)
    def test_third(self):           self.assertEqual(_idx("third"), 2)
    def test_the_first_one(self):   self.assertEqual(_idx("the first one"), 0)
    def test_open_first_profile(self): self.assertEqual(_idx("open first profile"), 0)
    def test_number_one(self):      self.assertEqual(_idx("number one"), 0)
    def test_profile_one(self):     self.assertEqual(_idx("profile one"), 0)
    def test_profile_1(self):       self.assertEqual(_idx("profile 1"), 0)
    def test_profile_two(self):     self.assertEqual(_idx("profile two"), 1)
    def test_profile_three(self):   self.assertEqual(_idx("profile three"), 2)
    def test_choose_one(self):      self.assertEqual(_idx("choose one"), 0)
    def test_select_one(self):      self.assertEqual(_idx("select one"), 0)


# ---------------------------------------------------------------------------
# 5. Alias phrases
# ---------------------------------------------------------------------------

class TestAliases(unittest.TestCase):

    def test_my_profile(self):      self.assertEqual(_idx("my profile"), 0)
    def test_mine(self):            self.assertEqual(_idx("mine"), 0)
    def test_default(self):         self.assertEqual(_idx("default"), 0)
    def test_gaming_profile(self):  self.assertEqual(_idx("gaming profile"), 1)
    def test_alias_case(self):      self.assertEqual(_idx("MY PROFILE"), 0)
    def test_alias_extra_space(self): self.assertEqual(_idx("  mine  "), 0)


# ---------------------------------------------------------------------------
# 6. Profile name matching (exact and fuzzy)
# ---------------------------------------------------------------------------

class TestNameMatching(unittest.TestCase):

    def test_muhammed_exact(self):      self.assertEqual(_idx("Muhammed"), 0)
    def test_muhammed_lower(self):      self.assertEqual(_idx("muhammed"), 0)
    def test_muhammed_upper(self):      self.assertEqual(_idx("MUHAMMED"), 0)
    def test_hashi_exact(self):         self.assertEqual(_idx("Hashi"), 1)
    def test_hashi_lower(self):         self.assertEqual(_idx("hashi"), 1)
    def test_hashi_upper(self):         self.assertEqual(_idx("HASHI"), 1)
    def test_amithcs_exact(self):       self.assertEqual(_idx("amithcs.in"), 2)
    def test_amithcs_upper(self):       self.assertEqual(_idx("AMITHCS.IN"), 2)

    # Fuzzy — slight speech-recognition mistakes
    def test_muhammed_typo(self):       self.assertEqual(_idx("muhamed"), 0)
    def test_muhammed_mishear(self):    self.assertEqual(_idx("mohammed"), 0)
    def test_hashi_mishear(self):       self.assertEqual(_idx("hashy"), 1)
    def test_hashi_mishear2(self):      self.assertEqual(_idx("hash"), 1)


# ---------------------------------------------------------------------------
# 7. Natural-language phrases (Profile 1)
# ---------------------------------------------------------------------------

class TestNaturalLanguageProfile1(unittest.TestCase):

    def test_number_one(self):          self.assertEqual(_idx("number one"), 0)
    def test_profile_one(self):         self.assertEqual(_idx("profile one"), 0)
    def test_profile_1(self):           self.assertEqual(_idx("profile 1"), 0)
    def test_the_first_one(self):       self.assertEqual(_idx("the first one"), 0)
    def test_choose_one(self):          self.assertEqual(_idx("choose one"), 0)
    def test_select_one(self):          self.assertEqual(_idx("select one"), 0)
    def test_open_first_profile(self):  self.assertEqual(_idx("open first profile"), 0)


# ---------------------------------------------------------------------------
# 8. Natural-language phrases (Profile 2)
# ---------------------------------------------------------------------------

class TestNaturalLanguageProfile2(unittest.TestCase):

    def test_two(self):                 self.assertEqual(_idx("two"), 1)
    def test_second(self):              self.assertEqual(_idx("second"), 1)
    def test_profile_two(self):         self.assertEqual(_idx("profile two"), 1)
    def test_hashi(self):               self.assertEqual(_idx("Hashi"), 1)
    def test_gaming_profile(self):      self.assertEqual(_idx("gaming profile"), 1)


# ---------------------------------------------------------------------------
# 9. Natural-language phrases (Profile 3)
# ---------------------------------------------------------------------------

class TestNaturalLanguageProfile3(unittest.TestCase):

    def test_three(self):               self.assertEqual(_idx("three"), 2)
    def test_third(self):               self.assertEqual(_idx("third"), 2)
    def test_profile_three(self):       self.assertEqual(_idx("profile three"), 2)
    def test_amithcs(self):             self.assertEqual(_idx("amithcs.in"), 2)


# ---------------------------------------------------------------------------
# 10. Confidence and low_confidence flag
# ---------------------------------------------------------------------------

class TestConfidence(unittest.TestCase):

    def test_exact_digit_is_100(self):
        self.assertEqual(_conf("1"), 100.0)

    def test_exact_ordinal_is_100(self):
        self.assertEqual(_conf("first"), 100.0)

    def test_exact_alias_is_100(self):
        self.assertEqual(_conf("mine"), 100.0)

    def test_exact_name_not_low_confidence(self):
        self.assertFalse(_low("Muhammed"))

    def test_exact_digit_not_low_confidence(self):
        self.assertFalse(_low("1"))

    def test_empty_string_is_low_confidence(self):
        self.assertTrue(_low(""))

    def test_gibberish_is_low_confidence(self):
        result = _parser().parse("xyzzy qwerty blorp")
        self.assertTrue(result.low_confidence)

    def test_low_confidence_threshold(self):
        # A very poor match should be flagged
        result = _parser().parse("zzz")
        self.assertTrue(result.low_confidence)


# ---------------------------------------------------------------------------
# 11. Edge cases
# ---------------------------------------------------------------------------

class TestEdgeCases(unittest.TestCase):

    def test_empty_string(self):
        self.assertEqual(_idx(""), -1)

    def test_whitespace_only(self):
        self.assertEqual(_idx("   "), -1)

    def test_cancel_not_matched(self):
        # "cancel" should not match any profile (low confidence)
        result = _parser().parse("cancel")
        self.assertTrue(result.low_confidence or result.index == -1)

    def test_out_of_range_digit(self):
        # "9" with only 3 candidates → no match
        self.assertEqual(_idx("9"), -1)

    def test_case_insensitive_ordinal(self):
        self.assertEqual(_idx("FIRST"), 0)
        self.assertEqual(_idx("Second"), 1)

    def test_extra_whitespace(self):
        self.assertEqual(_idx("  1  "), 0)
        self.assertEqual(_idx("  first  "), 0)

    def test_parse_result_fields(self):
        result = _parser().parse("1")
        self.assertEqual(result.index, 0)
        self.assertEqual(result.name, "Muhammed")
        self.assertEqual(result.confidence, 100.0)
        self.assertFalse(result.low_confidence)


# ---------------------------------------------------------------------------
# 12. _select_chrome_profile integration
# ---------------------------------------------------------------------------

class TestSelectChromeProfileIntent(unittest.TestCase):

    def _make_profiles(self, names):
        from automation.apps import _ChromeProfile
        return [_ChromeProfile(directory=f"Profile {i}", display_name=n)
                for i, n in enumerate(names, start=1)]

    def _select(self, profiles, spoken):
        from automation.apps import _select_chrome_profile
        it = iter([spoken])
        return _select_chrome_profile(profiles, voice_input=lambda: next(it))

    def setUp(self):
        self.profiles = self._make_profiles(["Muhammed", "Hashi", "amithcs.in"])

    # --- numeric ---
    def test_digit_1(self):     self.assertEqual(self._select(self.profiles, "1").display_name, "Muhammed")
    def test_digit_2(self):     self.assertEqual(self._select(self.profiles, "2").display_name, "Hashi")
    def test_digit_3(self):     self.assertEqual(self._select(self.profiles, "3").display_name, "amithcs.in")

    # --- spoken numbers ---
    def test_one(self):         self.assertEqual(self._select(self.profiles, "one").display_name, "Muhammed")
    def test_two(self):         self.assertEqual(self._select(self.profiles, "two").display_name, "Hashi")
    def test_three(self):       self.assertEqual(self._select(self.profiles, "three").display_name, "amithcs.in")

    # --- homophones ---
    def test_won(self):         self.assertEqual(self._select(self.profiles, "won").display_name, "Muhammed")
    def test_too(self):         self.assertEqual(self._select(self.profiles, "too").display_name, "Hashi")
    def test_free(self):        self.assertEqual(self._select(self.profiles, "free").display_name, "amithcs.in")

    # --- repeated tokens ---
    def test_1_1(self):         self.assertEqual(self._select(self.profiles, "1 1").display_name, "Muhammed")
    def test_one_one(self):     self.assertEqual(self._select(self.profiles, "one one").display_name, "Muhammed")

    # --- ordinals ---
    def test_first(self):       self.assertEqual(self._select(self.profiles, "first").display_name, "Muhammed")
    def test_second(self):      self.assertEqual(self._select(self.profiles, "second").display_name, "Hashi")
    def test_third(self):       self.assertEqual(self._select(self.profiles, "third").display_name, "amithcs.in")

    # --- natural language ---
    def test_the_first_one(self):
        self.assertEqual(self._select(self.profiles, "the first one").display_name, "Muhammed")
    def test_open_one(self):
        self.assertEqual(self._select(self.profiles, "open one").display_name, "Muhammed")
    def test_number_one(self):
        self.assertEqual(self._select(self.profiles, "number one").display_name, "Muhammed")
    def test_profile_one(self):
        self.assertEqual(self._select(self.profiles, "profile one").display_name, "Muhammed")
    def test_profile_two(self):
        self.assertEqual(self._select(self.profiles, "profile two").display_name, "Hashi")
    def test_open_first_profile(self):
        self.assertEqual(self._select(self.profiles, "open first profile").display_name, "Muhammed")

    # --- profile names ---
    def test_name_muhammed(self):
        self.assertEqual(self._select(self.profiles, "Muhammed").display_name, "Muhammed")
    def test_name_hashi_upper(self):
        self.assertEqual(self._select(self.profiles, "HASHI").display_name, "Hashi")
    def test_name_email(self):
        self.assertEqual(self._select(self.profiles, "amithcs.in").display_name, "amithcs.in")

    # --- aliases ---
    def test_mine(self):
        self.assertEqual(self._select(self.profiles, "mine").display_name, "Muhammed")
    def test_my_profile(self):
        self.assertEqual(self._select(self.profiles, "my profile").display_name, "Muhammed")
    def test_default(self):
        self.assertEqual(self._select(self.profiles, "default").display_name, "Muhammed")

    # --- cancel ---
    def test_cancel_raises(self):
        from automation.apps import AppOperationError, _select_chrome_profile
        with self.assertRaises(AppOperationError):
            _select_chrome_profile(self.profiles, voice_input=lambda: "cancel")

    # --- None from voice_input exhausts retries ---
    def test_none_exhausts_retries(self):
        from automation.apps import AppOperationError, _select_chrome_profile
        with self.assertRaises(AppOperationError):
            _select_chrome_profile(self.profiles, voice_input=lambda: None)

    # --- low-confidence triggers re-prompt then succeeds ---
    def test_low_confidence_then_success(self):
        from automation.apps import _select_chrome_profile
        responses = iter(["xyzzy qwerty blorp blorp", "1"])
        result = _select_chrome_profile(
            self.profiles,
            voice_input=lambda: next(responses),
        )
        self.assertEqual(result.display_name, "Muhammed")


if __name__ == "__main__":
    unittest.main(verbosity=2)
