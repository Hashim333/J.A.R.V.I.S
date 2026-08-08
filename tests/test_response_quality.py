"""
tests/test_response_quality.py

Regression tests for the "wrong Done reply" / "generic response" bug.

Every user-facing message produced by the pipeline must be contextual:
it must never be a bare "Done." / "OK." / "Completed." / "Unknown command",
and it must never address the user by name (e.g. "Yes Hashim").
"""

from __future__ import annotations

import unittest

from executor.executor import Executor
from executor.registry import Registry
from models.response import Response
from response.formatter import ResponseFormatter
from response.manager import ResponseManager
from thinking.response_generator import ResponseGenerator

BANNED_PHRASES = (
    "done.",
    "done",
    "ok.",
    "ok",
    "okay.",
    "completed.",
    "action completed.",
    "unknown command.",
    "task completed successfully.",
    "search complete.",
)
BANNED_NAMES = ("hashim", "muhammad", "muhammed", "hassan", "ahmed")


def _lower(text: str) -> str:
    return " ".join((text or "").split()).casefold()


class TestResponseGeneratorQuality(unittest.TestCase):
    def setUp(self) -> None:
        self.generator = ResponseGenerator()

    def _generate(self, intent: str, data: dict) -> str:
        resp = self.generator.generate(
            executor_response=Response(
                success=True, message="", data=data,
            ),
            intent=intent,
            raw_text="",
        )
        return resp.message

    def test_open_app_contextual(self) -> None:
        self.assertEqual(
            self._generate("open_app", {"app_name": "Chrome"}),
            "Chrome is now open.",
        )

    def test_focus_app_contextual(self) -> None:
        self.assertEqual(
            self._generate("focus_app", {"app_name": "Chrome"}),
            "Switching to Chrome.",
        )

    def test_close_app_contextual(self) -> None:
        self.assertEqual(
            self._generate("close_app", {"app_name": "Chrome"}),
            "Chrome has been closed.",
        )

    def test_open_website_contextual(self) -> None:
        self.assertEqual(
            self._generate("open_website", {"website": "google.com"}),
            "Opened google.com.",
        )

    def test_search_contextual(self) -> None:
        msg = self._generate("search", {"query": "weather", "provider": "google"})
        self.assertIn("weather", msg)
        self.assertIn("Google", msg)

    def test_no_generic_phrases_any_intent(self) -> None:
        intents_with_data = [
            ("open_app", {"app_name": "Notepad"}),
            ("close_app", {"app_name": "Notepad"}),
            ("focus_app", {"app_name": "Notepad"}),
            ("open_website", {"website": "github.com"}),
            ("search", {"query": "cats"}),
            ("play_music", {"query": "lofi"}),
            ("screenshot", {}),
            ("lock", {}),
            ("noop", {}),
            ("unknown_intent", {}),
        ]
        for intent, data in intents_with_data:
            msg = self._generate(intent, data)
            lowered = _lower(msg)
            self.assertTrue(msg, f"intent {intent} produced empty message")
            for banned in BANNED_PHRASES:
                self.assertNotEqual(lowered, banned, f"intent {intent} -> {msg!r}")
            for name in BANNED_NAMES:
                self.assertNotIn(name, lowered, f"intent {intent} -> {msg!r}")


class TestResponseFormatterQuality(unittest.TestCase):
    def test_fallback_messages_are_not_generic(self) -> None:
        formatter = ResponseFormatter()
        for intent in ("open_app", "open_website", "search", "play_music", "something"):
            msg = formatter._fallback_success_message(
                intent, {"app_name": "Chrome", "website": "github.com",
                         "query": "news", "provider": "google"},
            )
            lowered = _lower(msg)
            self.assertTrue(msg)
            for banned in BANNED_PHRASES:
                self.assertNotEqual(lowered, banned)
                self.assertNotIn("done", lowered)

    def test_formatter_success_uses_contextual_message(self) -> None:
        response = Response(
            success=True,
            message="Chrome is now open.",
            data={"intent": "open_app"},
        )
        text = ResponseManager().console_text(response)
        self.assertEqual(text, "Chrome is now open.")

    def test_no_bare_done_fallback(self) -> None:
        response = Response(
            success=True,
            message="All steps executed.",
            data={"intent": "open_app", "app_name": "Chrome"},
        )
        text = ResponseManager().console_text(response)
        self.assertIn("Chrome", text)
        self.assertNotEqual(_lower(text), "done.")


class TestExecutorNoop(unittest.TestCase):
    def test_empty_plan_noop_is_contextual(self) -> None:
        from brain.execution_plan import ExecutionPlan

        executor = Executor(Registry())
        plan = ExecutionPlan(
            raw_text="continue",
            intent="noop",
            confidence=1.0,
            steps=[],
        )
        result = executor.execute(plan)
        self.assertTrue(result.success)
        self.assertEqual(result.message, "Okay, no action taken.")

    def test_empty_plan_unsupported_is_helpful(self) -> None:
        from brain.execution_plan import ExecutionPlan

        executor = Executor(Registry())
        plan = ExecutionPlan(
            raw_text="do nothing",
            intent="no_op",
            confidence=1.0,
            steps=[],
        )
        result = executor.execute(plan)
        self.assertFalse(result.success)
        self.assertIn("isn't something I can execute yet", result.message)


if __name__ == "__main__":
    unittest.main()
