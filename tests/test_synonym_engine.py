"""
tests/test_synonym_engine.py

Unit tests for voice/synonym_engine.py — canonicalising recognised speech
into the canonical phrases the intent parser understands (FIX-002 Synonym
Engine).

Covers the spec's example mappings:

    play music / play a song / start music / music please  -> play music
    open up chrome / open the browser                      -> open chrome / open browser
    turn up the volume                                     -> volume up
"""

from __future__ import annotations

import unittest

from voice.synonym_engine import CanonicalResult, SynonymEngine


class TestSynonymEngineMedia(unittest.TestCase):
    """Requirement: every music phrasing collapses onto ``play music``."""

    def test_identity_play_music_unchanged(self) -> None:
        result = SynonymEngine.canonicalize("play music")
        self.assertIsInstance(result, CanonicalResult)
        self.assertEqual(result.text, "play music")
        self.assertFalse(result.changed)

    def test_play_a_song(self) -> None:
        self.assertEqual(SynonymEngine.canonicalize("play a song").text, "play music")

    def test_start_music(self) -> None:
        result = SynonymEngine.canonicalize("start music")
        self.assertEqual(result.text, "play music")
        self.assertEqual(result.raw, "start music")
        self.assertTrue(result.changed)
        self.assertEqual(result.changes, [("start music", "play music")])

    def test_music_please(self) -> None:
        self.assertEqual(SynonymEngine.canonicalize("music please").text, "play music")

    def test_play_some_music(self) -> None:
        self.assertEqual(SynonymEngine.canonicalize("play some music").text, "play music")

    def test_play_the_song(self) -> None:
        self.assertEqual(SynonymEngine.canonicalize("play the song").text, "play music")

    def test_put_on_music(self) -> None:
        self.assertEqual(SynonymEngine.canonicalize("put on music").text, "play music")


class TestSynonymEngineApps(unittest.TestCase):
    """Requirement: browser/app phrasings collapse onto ``open <app>``."""

    def test_open_up_chrome(self) -> None:
        self.assertEqual(SynonymEngine.canonicalize("open up chrome").text, "open chrome")

    def test_open_the_browser(self) -> None:
        self.assertEqual(SynonymEngine.canonicalize("open the browser").text, "open browser")

    def test_launch_the_browser(self) -> None:
        self.assertEqual(SynonymEngine.canonicalize("launch the browser").text, "open browser")

    def test_browser_please(self) -> None:
        self.assertEqual(SynonymEngine.canonicalize("browser please").text, "open browser")

    def test_open_google_chrome(self) -> None:
        self.assertEqual(SynonymEngine.canonicalize("open google chrome").text, "open chrome")


class TestSynonymEngineVolume(unittest.TestCase):
    """Volume phrasings the parser's verb table needs help with."""

    def test_turn_up_the_volume(self) -> None:
        self.assertEqual(SynonymEngine.canonicalize("turn up the volume").text, "volume up")

    def test_turn_the_volume_down(self) -> None:
        self.assertEqual(
            SynonymEngine.canonicalize("turn the volume down").text, "decrease volume"
        )

    def test_mute_the_volume(self) -> None:
        self.assertEqual(SynonymEngine.canonicalize("mute the volume").text, "mute volume")


class TestSynonymEngineSafety(unittest.TestCase):
    """Never mangle a real query — rewrites are whole-utterance only."""

    def test_search_query_untouched(self) -> None:
        result = SynonymEngine.canonicalize("search relaxing music")
        self.assertEqual(result.text, "search relaxing music")
        self.assertFalse(result.changed)

    def test_multi_command_untouched(self) -> None:
        result = SynonymEngine.canonicalize("open chrome and search chatgpt")
        self.assertEqual(result.text, "open chrome and search chatgpt")
        self.assertFalse(result.changed)

    def test_empty_untouched(self) -> None:
        result = SynonymEngine.canonicalize("   ")
        self.assertEqual(result.text, "")
        self.assertFalse(result.changed)

    def test_punctuation_normalised_for_matching(self) -> None:
        self.assertEqual(SynonymEngine.canonicalize("start music!").text, "play music")

    def test_case_insensitive(self) -> None:
        self.assertEqual(SynonymEngine.canonicalize("START MUSIC").text, "play music")


if __name__ == "__main__":
    unittest.main()
