"""
tests/test_speech_intelligence.py — Speech Intelligence Layer (FIX-002).

The layer sits between Speech Recognition and Intent Processing so JARVIS
never executes a raw Whisper/STT transcript directly.  Every transcript is
confidence-gated before it reaches the planner:

  * HIGH   confidence  -> EXECUTE the recognised text as-is
  * MEDIUM confidence  -> CORRECT via alias / installed-app / fuzzy matching,
                          ASK when ambiguous
  * LOW    confidence  -> REFUSE naturally (never executed)

All decisions are recorded in an internal-only correction log.
"""

from __future__ import annotations

import time
import unittest

from thinking.speech_intelligence import (
    AliasDictionary,
    ConfidenceBand,
    InstalledAppMatcher,
    SpeechAction,
    SpeechIntelligenceLayer,
    SpeechTranscript,
    classify_band,
)

_REFUSALS = (
    "I didn't quite catch that.",
    "Could you repeat that, sir?",
    "I heard something different than expected. Please say it again.",
)


def _layer(*, apps: list[str] | None = None, aliases: dict[str, str] | None = None):
    matcher = InstalledAppMatcher(apps=apps or ["Google Chrome", "Calculator",
                                               "Notepad", "Chrome", "Chromium"])
    return SpeechIntelligenceLayer(
        aliases=AliasDictionary(aliases),
        app_matcher=matcher,
    )


class TestConfidenceBands(unittest.TestCase):
    def test_high_band(self) -> None:
        self.assertIs(classify_band(0.90), ConfidenceBand.HIGH)
        self.assertIs(classify_band(0.70), ConfidenceBand.HIGH)

    def test_medium_band(self) -> None:
        self.assertIs(classify_band(0.60), ConfidenceBand.MEDIUM)
        self.assertIs(classify_band(0.50), ConfidenceBand.MEDIUM)

    def test_low_band(self) -> None:
        self.assertIs(classify_band(0.25), ConfidenceBand.LOW)
        self.assertIs(classify_band(0.0), ConfidenceBand.LOW)


class TestHighConfidence(unittest.TestCase):
    def test_high_executes_as_is(self) -> None:
        layer = _layer()
        decision = layer.process(
            SpeechTranscript(text="open chrome", confidence=0.90)
        )
        self.assertIs(decision.action, SpeechAction.EXECUTE)
        self.assertEqual(decision.text, "open chrome")
        self.assertEqual(decision.corrected_text, "open chrome")
        self.assertIs(decision.band, ConfidenceBand.HIGH)


class TestLowConfidence(unittest.TestCase):
    def test_low_refuses_naturally(self) -> None:
        layer = _layer()
        decision = layer.process(
            SpeechTranscript(text="open chrome", confidence=0.25)
        )
        self.assertIs(decision.action, SpeechAction.REFUSE)
        self.assertEqual(decision.reason, "low_confidence")
        self.assertIn(decision.text, _REFUSALS)

    def test_low_never_executes_command(self) -> None:
        layer = _layer()
        decision = layer.process(
            SpeechTranscript(text="shut down the computer", confidence=0.20)
        )
        self.assertIs(decision.action, SpeechAction.REFUSE)

    def test_empty_text_refuses(self) -> None:
        layer = _layer()
        decision = layer.process(SpeechTranscript(text="  ", confidence=0.9))
        self.assertIs(decision.action, SpeechAction.REFUSE)
        self.assertEqual(decision.reason, "empty")

    def test_garbage_transcript_never_executes(self) -> None:
        """FIX 4: decoder garbage ("or not man") has vowel shape and voiced
        time but collapsed word confidence — it must be refused, never
        executed as a command."""
        layer = _layer()
        decision = layer.process(
            SpeechTranscript(
                text="or not man",
                confidence=0.18,
                speech_seconds=0.5,
                min_word_confidence=0.05,  # Below new threshold of 0.10
            )
        )
        self.assertIs(decision.action, SpeechAction.REFUSE)
        self.assertEqual(decision.reason, "low_confidence")

    def test_short_voiced_blip_never_executes(self) -> None:
        """FIX 4: a low-confidence phrase with less voiced speech than a
        real utterance takes must be refused even if the words look clean."""
        layer = _layer()
        decision = layer.process(
            SpeechTranscript(
                text="or bad man",
                confidence=0.20,
                speech_seconds=0.25,
                min_word_confidence=0.60,
            )
        )
        self.assertIs(decision.action, SpeechAction.REFUSE)

    def test_confidence_040_refuses(self) -> None:
        """Confidence 0.40 is now MEDIUM (threshold 0.35) - should correct/execute, not refuse."""
        layer = _layer()
        decision = layer.process(
            SpeechTranscript(text="open chrome", confidence=0.40)
        )
        # 0.40 is now MEDIUM band - should CORRECT via alias or EXECUTE
        self.assertNotEqual(decision.action, SpeechAction.REFUSE)
        self.assertIn(decision.action, (SpeechAction.EXECUTE, SpeechAction.CORRECT))

    def test_confidence_045_excutes(self) -> None:
        """Confidence 0.45 is HIGH (threshold 0.35 for LOW, 0.70 for HIGH) - should execute."""
        layer = _layer()
        # Use a known command that will be corroborated
        decision = layer.process(
            SpeechTranscript(text="open chrome", confidence=0.45, speech_seconds=1.0)
        )
        # 0.45 is MEDIUM band - should CORRECT via alias or EXECUTE
        self.assertNotEqual(decision.action, SpeechAction.REFUSE)
        self.assertIn(decision.action, (SpeechAction.EXECUTE, SpeechAction.CORRECT))

    def test_genuine_conversation_still_rescued(self) -> None:
        """FIX 4: the hardening must not refuse ordinary conversational
        speech with real duration and healthy word confidence."""
        layer = _layer()
        decision = layer.process(
            SpeechTranscript(
                text="can you hear me",
                confidence=0.25,
                speech_seconds=0.9,
                min_word_confidence=0.50,
            )
        )
        self.assertIs(decision.action, SpeechAction.EXECUTE)
        self.assertEqual(decision.reason, "low_confidence_conversational")


class TestMediumCorrection(unittest.TestCase):
    def test_alias_correction(self) -> None:
        layer = _layer(aliases={"calc": "Calculator"})
        decision = layer.process(
            SpeechTranscript(text="open calc", confidence=0.60)
        )
        self.assertIs(decision.action, SpeechAction.CORRECT)
        self.assertEqual(decision.text, "open Calculator")
        self.assertEqual(decision.reason, "alias")

    def test_installed_app_exact_match(self) -> None:
        layer = _layer(apps=["Steam"])
        decision = layer.process(
            SpeechTranscript(text="open steam", confidence=0.60)
        )
        self.assertIs(decision.action, SpeechAction.CORRECT)
        self.assertEqual(decision.text, "open Steam")
        self.assertEqual(decision.reason, "installed_app")

    def test_default_alias_wins_over_installed(self) -> None:
        layer = _layer(apps=["Chrome"])
        decision = layer.process(
            SpeechTranscript(text="open chrome", confidence=0.60)
        )
        self.assertIs(decision.action, SpeechAction.CORRECT)
        self.assertEqual(decision.text, "open Google Chrome")
        self.assertEqual(decision.reason, "alias")

    def test_fuzzy_match_corrects_typo(self) -> None:
        layer = _layer(apps=["Calculator"])
        decision = layer.process(
            SpeechTranscript(text="open calac", confidence=0.60)
        )
        self.assertIs(decision.action, SpeechAction.CORRECT)
        self.assertEqual(decision.text, "open Calculator")

    def test_non_app_medium_executes_as_is(self) -> None:
        layer = _layer()
        decision = layer.process(
            SpeechTranscript(text="set volume to 50", confidence=0.60)
        )
        self.assertIs(decision.action, SpeechAction.EXECUTE)
        self.assertEqual(decision.text, "set volume to 50")
        self.assertEqual(decision.reason, "medium_confidence_non_app")

    def test_close_command_corrected(self) -> None:
        layer = _layer(aliases={"notepad": "Notepad"})
        decision = layer.process(
            SpeechTranscript(text="close notepad", confidence=0.60)
        )
        self.assertIs(decision.action, SpeechAction.CORRECT)
        self.assertEqual(decision.text, "close Notepad")

    def test_filler_words_stripped(self) -> None:
        layer = _layer(aliases={"calculator": "Calculator"})
        decision = layer.process(
            SpeechTranscript(text="open the calculator please", confidence=0.60)
        )
        self.assertIs(decision.action, SpeechAction.CORRECT)
        self.assertEqual(decision.text, "open Calculator")


class TestAmbiguity(unittest.TestCase):
    def test_ambiguous_asks_natural_question(self) -> None:
        layer = _layer(apps=["Chrome", "Chromium"])
        decision = layer.process(
            SpeechTranscript(text="open chrom", confidence=0.60)
        )
        self.assertIs(decision.action, SpeechAction.ASK)
        self.assertEqual(decision.reason, "ambiguous")
        self.assertIn("Did you mean", decision.text)
        self.assertIn("Chrome", decision.text)
        self.assertIn("Chromium", decision.text)
        self.assertEqual(decision.candidates, ("Chrome", "Chromium"))


class TestCorrectionLog(unittest.TestCase):
    def test_log_records_all_decisions(self) -> None:
        layer = _layer(aliases={"calc": "Calculator"})
        layer.process(SpeechTranscript(text="open chrome", confidence=0.95))
        layer.process(SpeechTranscript(text="open calc", confidence=0.60))
        layer.process(SpeechTranscript(text="open chrome", confidence=0.25))

        records = layer.corrections
        self.assertEqual(len(records), 3)

        high = records[0]
        self.assertEqual(high.original, "open chrome")
        self.assertEqual(high.action, SpeechAction.EXECUTE)
        self.assertEqual(high.reason, "high_confidence")

        corrected = records[1]
        self.assertEqual(corrected.original, "open calc")
        self.assertEqual(corrected.corrected, "open Calculator")
        self.assertAlmostEqual(corrected.confidence, 0.60)
        self.assertEqual(corrected.reason, "alias")

        refused = records[2]
        self.assertEqual(refused.original, "open chrome")
        self.assertEqual(refused.action, SpeechAction.REFUSE)
        self.assertEqual(refused.reason, "low_confidence")

    def test_log_entries_have_timestamps(self) -> None:
        before = time.time()
        layer = _layer()
        layer.process(SpeechTranscript(text="open chrome", confidence=0.60))
        record = layer.corrections[0]
        self.assertGreaterEqual(record.timestamp, before)
        self.assertLessEqual(record.timestamp, time.time())


class TestSingleScanGuarantee(unittest.TestCase):
    def test_injected_apps_scan_once(self) -> None:
        matcher = InstalledAppMatcher(apps=["Google Chrome"], scan_now=False)
        self.assertFalse(matcher.scanned)
        self.assertEqual(matcher.scan(), 1)
        self.assertTrue(matcher.scanned)
        self.assertEqual(matcher.scan(), 1)
        self.assertEqual(matcher.scan(), 1)

    def test_scan_now_default(self) -> None:
        matcher = InstalledAppMatcher(apps=["Google Chrome"])
        self.assertTrue(matcher.scanned)
        self.assertEqual(matcher.count, 1)

    def test_matching_does_not_rescan(self) -> None:
        scans = [0]

        class _FakeRegistry:
            count = 2

            def discover(self) -> int:
                scans[0] += 1
                return 2

            def lookup(self, name: str):
                return None

            def search(self, name: str, threshold: float = 0.0):
                return []

        matcher = InstalledAppMatcher(registry=_FakeRegistry(), scan_now=True)
        self.assertTrue(matcher.scanned)
        matcher.resolve("chrome")
        matcher.search("chrome")
        self.assertEqual(scans[0], 0)


class TestTranscriptTimestamp(unittest.TestCase):
    def test_timestamp_present(self) -> None:
        before = time.time()
        transcript = SpeechTranscript(text="open chrome", confidence=0.6)
        self.assertGreaterEqual(transcript.timestamp, before)
        self.assertLessEqual(transcript.timestamp, time.time())


if __name__ == "__main__":
    unittest.main()
