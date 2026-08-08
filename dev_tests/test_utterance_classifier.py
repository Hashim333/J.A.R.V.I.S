import unittest
from unittest.mock import MagicMock

from thinking.utterance_classifier import (
    ACTION_CATEGORIES,
    NON_ACTION_CATEGORIES,
    ClassificationResult,
    UtteranceCategory,
    UtteranceClassifier,
)


class _OfflineLLM:
    """Simulates an unreachable Ollama so the fallback heuristics run."""

    def ask(self, prompt):
        raise RuntimeError("offline")


class _ScriptedLLM:
    """Returns a fixed classification response."""

    def __init__(self, raw: str):
        self._raw = raw

    def ask(self, prompt):
        return self._raw


class TestCategorySets(unittest.TestCase):
    def test_non_action_never_contains_action(self):
        self.assertTrue(NON_ACTION_CATEGORIES.isdisjoint(ACTION_CATEGORIES))

    def test_all_nine_categories_accounted_for(self):
        all_categories = set(UtteranceCategory)
        self.assertEqual(
            all_categories,
            NON_ACTION_CATEGORIES | ACTION_CATEGORIES,
        )


class TestRuleFastPath(unittest.TestCase):
    def setUp(self):
        self.classifier = UtteranceClassifier(llm=_OfflineLLM())

    def test_open_app(self):
        r = self.classifier.classify("open chrome")
        self.assertEqual(r.category, UtteranceCategory.APPLICATION_CONTROL)
        self.assertEqual(r.source, "rules")

    def test_close_app(self):
        r = self.classifier.classify("close notepad")
        self.assertEqual(r.category, UtteranceCategory.APPLICATION_CONTROL)

    def test_volume(self):
        r = self.classifier.classify("increase volume")
        self.assertEqual(r.category, UtteranceCategory.SYSTEM_COMMAND)

    def test_website(self):
        r = self.classifier.classify("open youtube")
        self.assertEqual(r.category, UtteranceCategory.BROWSER_CONTROL)

    def test_media(self):
        r = self.classifier.classify("play some music")
        self.assertEqual(r.category, UtteranceCategory.MEDIA_CONTROL)

    def test_action_category_has_empty_response(self):
        r = self.classifier.classify("open chrome")
        self.assertEqual(r.response, "")

    def test_unknown_intent_falls_through_to_llm_path(self):
        r = self.classifier.classify("the quick brown fox jumps over the lazy dog")
        self.assertNotEqual(r.category, UtteranceCategory.APPLICATION_CONTROL)


class TestCannedPath(unittest.TestCase):
    def setUp(self):
        self.classifier = UtteranceClassifier(llm=_OfflineLLM())

    def test_can_you_hear_me(self):
        r = self.classifier.classify("can you hear me")
        self.assertEqual(r.category, UtteranceCategory.QUESTION)
        self.assertIn("loud and clear", r.response)

    def test_identity(self):
        r = self.classifier.classify("who are you")
        self.assertEqual(r.category, UtteranceCategory.QUESTION)
        self.assertIn("JARVIS", r.response)

    def test_greeting(self):
        r = self.classifier.classify("hey jarvis")
        self.assertEqual(r.category, UtteranceCategory.CHAT)

    def test_confirmation(self):
        r = self.classifier.classify("yes")
        self.assertEqual(r.category, UtteranceCategory.CONFIRMATION)

    def test_cancellation(self):
        r = self.classifier.classify("no")
        self.assertEqual(r.category, UtteranceCategory.CANCELLATION)

    def test_no_thanks_is_cancellation_not_chat(self):
        r = self.classifier.classify("no thanks")
        self.assertEqual(r.category, UtteranceCategory.CANCELLATION)

    def test_empty_input(self):
        r = self.classifier.classify("")
        self.assertEqual(r.category, UtteranceCategory.CHAT)

    def test_question_mark_falls_to_question(self):
        r = self.classifier.classify("is it going to rain tomorrow?")
        self.assertEqual(r.category, UtteranceCategory.QUESTION)


class TestLLMPath(unittest.TestCase):
    def test_parses_classification_and_response(self):
        classifier = UtteranceClassifier(
            llm=_ScriptedLLM("CLASSIFICATION: CHAT\nRESPONSE: Hello there!")
        )
        r = classifier.classify("anything")
        self.assertEqual(r.category, UtteranceCategory.CHAT)
        self.assertEqual(r.source, "llm")
        self.assertEqual(r.response, "Hello there!")

    def test_guard_downgrades_action_mislabels_to_question(self):
        classifier = UtteranceClassifier(
            llm=_ScriptedLLM("CLASSIFICATION: SYSTEM_COMMAND\nRESPONSE: ")
        )
        r = classifier.classify("am i late for the meeting")
        self.assertEqual(r.category, UtteranceCategory.QUESTION)
        self.assertEqual(r.source, "llm+guard")

    def test_guard_allows_real_action_command(self):
        classifier = UtteranceClassifier(
            llm=_ScriptedLLM("CLASSIFICATION: SYSTEM_COMMAND\nRESPONSE: ")
        )
        r = classifier.classify("turn off the computer now")
        self.assertEqual(r.category, UtteranceCategory.SYSTEM_COMMAND)

    def test_unparseable_llm_falls_back(self):
        classifier = UtteranceClassifier(llm=_ScriptedLLM("no structured output at all"))
        r = classifier.classify("hello")
        self.assertIsNotNone(r.category)


class TestParseLLMResponse(unittest.TestCase):
    def test_unknown_category_rejected(self):
        self.assertIsNone(UtteranceClassifier._parse_llm_response("CLASSIFICATION: NOPE"))

    def test_missing_classification_rejected(self):
        self.assertIsNone(UtteranceClassifier._parse_llm_response("just some text"))

    def test_case_insensitive(self):
        result = UtteranceClassifier._parse_llm_response("classification: chat\nresponse: hi")
        self.assertEqual(result.category, UtteranceCategory.CHAT)

    def test_multiline_response(self):
        result = UtteranceClassifier._parse_llm_response(
            "CLASSIFICATION: CHAT\nRESPONSE: Line one\nLine two"
        )
        self.assertEqual(result.response, "Line one\nLine two")


if __name__ == "__main__":
    unittest.main()
