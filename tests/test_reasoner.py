"""
tests/test_reasoner.py

Tests for the LLM reasoning layer (thinking/reasoner.py): mode decisions,
confidence clamping, structured-JSON parsing, alternative strategies, and
the fallback contract (never raises, returns None when the LLM is down).
"""

from __future__ import annotations

import unittest

from thinking.reasoner import Reasoner, ReasonedPlan


class FakeLLM:
    """Deterministic stand-in for brain.llm.LLM."""

    def __init__(self, response=None, error=None) -> None:
        self._response = response
        self._error = error
        self.prompts: list[str] = []

    def ask(self, prompt: str) -> str:
        self.prompts.append(prompt)
        if self._error is not None:
            raise self._error
        return self._response


class TestReasonerModeDecision(unittest.TestCase):
    def _reasoner(self, llm: FakeLLM) -> Reasoner:
        return Reasoner(llm=llm)

    def test_act_mode(self) -> None:
        payload = (
            '{"mode": "ACT", "intent": "open_app", "entities": {"app_name": "chrome"}, '
            '"confidence": 0.95, "reasoning": "User wants Chrome open."}'
        )
        plan = self._reasoner(FakeLLM(payload)).reason("open chrome")
        self.assertIsInstance(plan, ReasonedPlan)
        self.assertEqual(plan.mode, "ACT")
        self.assertEqual(plan.intent, "open_app")
        self.assertEqual(plan.entities, {"app_name": "chrome"})
        self.assertAlmostEqual(plan.confidence, 0.95)
        self.assertTrue(plan.is_action)

    def test_ask_mode(self) -> None:
        payload = (
            '{"mode": "ASK", "intent": "open_app", "entities": {}, '
            '"confidence": 0.4, "question": "Which app should I open?", "reasoning": "Missing app."}'
        )
        plan = self._reasoner(FakeLLM(payload)).reason("open something")
        self.assertEqual(plan.mode, "ASK")
        self.assertEqual(plan.question, "Which app should I open?")

    def test_answer_mode(self) -> None:
        payload = (
            '{"mode": "ANSWER", "intent": "", "entities": {}, "confidence": 0.8, '
            '"answer": "I\'m JARVIS, your desktop assistant.", "reasoning": "Identity question."}'
        )
        plan = self._reasoner(FakeLLM(payload)).reason("who are you")
        self.assertEqual(plan.mode, "ANSWER")
        self.assertEqual(plan.answer, "I'm JARVIS, your desktop assistant.")

    def test_unknown_mode_returns_none(self) -> None:
        payload = '{"mode": "RUN_AWAY", "intent": "open_app", "confidence": 0.5}'
        self.assertIsNone(self._reasoner(FakeLLM(payload)).reason("open chrome"))

    def test_act_with_unknown_intent_downgraded_to_ask(self) -> None:
        payload = '{"mode": "ACT", "intent": "bake_cake", "entities": {}, "confidence": 0.9}'
        plan = self._reasoner(FakeLLM(payload)).reason("bake a cake")
        self.assertIsNotNone(plan)
        self.assertEqual(plan.mode, "ASK")


class TestReasonerFallback(unittest.TestCase):
    def test_llm_unreachable_returns_none(self) -> None:
        reasoner = Reasoner(llm=FakeLLM(error=RuntimeError("ollama down")))
        self.assertIsNone(reasoner.reason("open chrome"))

    def test_slow_llm_times_out_and_falls_back(self) -> None:
        import time

        class SlowLLM(FakeLLM):
            def ask(self, prompt):
                time.sleep(2.0)
                return '{"mode": "ANSWER", "intent": "", "confidence": 0.9, "answer": "hi"}'

        started = time.monotonic()
        plan = Reasoner(llm=SlowLLM(), timeout=0.2).reason("open chrome")
        elapsed = time.monotonic() - started

        self.assertIsNone(plan)
        self.assertLess(elapsed, 1.5, "reasoner must not block past its bound")

    def test_empty_text_returns_none(self) -> None:
        reasoner = Reasoner(llm=FakeLLM('{"mode": "ANSWER", "confidence": 0.5}'))
        self.assertIsNone(reasoner.reason("   "))

    def test_unparseable_output_returns_none(self) -> None:
        reasoner = Reasoner(llm=FakeLLM("sure, I can open that for you"))
        self.assertIsNone(reasoner.reason("open chrome"))

    def test_non_dict_json_returns_none(self) -> None:
        reasoner = Reasoner(llm=FakeLLM("[1, 2, 3]"))
        self.assertIsNone(reasoner.reason("open chrome"))


class TestReasonerConfidence(unittest.TestCase):
    def test_confidence_clamped_high(self) -> None:
        payload = '{"mode": "ANSWER", "intent": "", "confidence": 7.5, "answer": "hi"}'
        plan = Reasoner(llm=FakeLLM(payload)).reason("hi")
        self.assertAlmostEqual(plan.confidence, 1.0)

    def test_confidence_clamped_low(self) -> None:
        payload = '{"mode": "ANSWER", "intent": "", "confidence": -3, "answer": "hi"}'
        plan = Reasoner(llm=FakeLLM(payload)).reason("hi")
        self.assertAlmostEqual(plan.confidence, 0.0)

    def test_confidence_missing_defaults(self) -> None:
        payload = '{"mode": "ANSWER", "intent": "", "answer": "hi"}'
        plan = Reasoner(llm=FakeLLM(payload)).reason("hi")
        self.assertAlmostEqual(plan.confidence, 0.5)


class TestReasonerAlternatives(unittest.TestCase):
    def test_alternatives_parsed(self) -> None:
        payload = (
            '{"mode": "ACT", "intent": "open_app", "entities": {"app_name": "spotify"}, '
            '"confidence": 0.9, "alternatives": [{"intent": "open_website", '
            '"entities": {"website": "spotify.com"}, "description": "open in browser"}]}'
        )
        plan = Reasoner(llm=FakeLLM(payload)).reason("open spotify")
        self.assertEqual(len(plan.alternatives), 1)
        self.assertEqual(plan.alternatives[0].intent, "open_website")
        self.assertEqual(plan.alternatives[0].entities, {"website": "spotify.com"})

    def test_invalid_alternatives_filtered(self) -> None:
        payload = (
            '{"mode": "ACT", "intent": "open_app", "entities": {}, "confidence": 0.9, '
            '"alternatives": [{"intent": "bake_cake", "entities": {}}, "not-a-dict", '
            '{"intent": "search", "entities": {"query": "x"}}]}'
        )
        plan = Reasoner(llm=FakeLLM(payload)).reason("open spotify")
        self.assertEqual(len(plan.alternatives), 1)
        self.assertEqual(plan.alternatives[0].intent, "search")


class TestReasonerConversation(unittest.TestCase):
    def test_continue_reasons_with_answer(self) -> None:
        payload = (
            '{"mode": "ACT", "intent": "focus_app", "entities": {"app_name": "chrome"}, '
            '"confidence": 0.9, "reasoning": "User picked Chrome."}'
        )
        reasoner = Reasoner(llm=FakeLLM(payload))
        plan = reasoner.continue_(
            original_text="open the browser", question="Which browser?",
            answer="Chrome",
        )
        self.assertIsNotNone(plan)
        self.assertEqual(plan.mode, "ACT")
        self.assertEqual(plan.intent, "focus_app")

    def test_history_included_in_prompt(self) -> None:
        class HistoryEntry:
            content = "play music"

        class Memory:
            def get_recent_commands(self, limit=5):
                return [HistoryEntry()]

        llm = FakeLLM('{"mode": "ANSWER", "intent": "", "confidence": 0.5, "answer": "ok"}')
        Reasoner(llm=llm).reason("do it again", memory=Memory())
        self.assertTrue(any("play music" in p for p in llm.prompts))


if __name__ == "__main__":
    unittest.main()
