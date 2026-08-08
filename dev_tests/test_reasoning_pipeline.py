from __future__ import annotations

import unittest

from brain.parsed_command import ParsedCommand
from brain.planner import Planner
from models.response import Response
from services.conversation_manager import ConversationManager
from thinking.response_generator import ResponseGenerator


class TestReasoningPipeline(unittest.TestCase):
    def test_planner_adds_reasoning_pipeline_metadata(self) -> None:
        planner = Planner()
        parsed = ParsedCommand(raw_text="open chrome", intent="open_app", entities={"app_name": "chrome"})

        plan = planner.create_plan(parsed)

        self.assertIn("reasoning_pipeline", plan.metadata)
        self.assertEqual(plan.metadata["reasoning_pipeline"], ["observe", "understand", "plan", "verify", "act"])
        self.assertIn("observe", plan.metadata["reasoning"])

    def test_response_generator_uses_failure_context(self) -> None:
        generator = ResponseGenerator()
        response = Response(
            success=False,
            message="Failed.",
            error="Ctrl+N failed",
            data={"reason": "The browser shortcut was rejected", "recovery": "I will try a different method"},
        )

        result = generator.generate(response, intent="open_app", raw_text="open chrome")

        self.assertTrue(result.success is False)
        self.assertIn("browser shortcut", result.message.lower())
        self.assertIn("different method", result.message.lower())

    def test_conversation_manager_can_pause_and_resume(self) -> None:
        manager = ConversationManager()
        manager.pause("user interrupted")
        self.assertTrue(manager.is_paused)

        manager.resume()
        self.assertFalse(manager.is_paused)
        self.assertEqual(manager.last_interruption_reason, "user interrupted")
