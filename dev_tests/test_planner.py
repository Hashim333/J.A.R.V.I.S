"""
dev_tests/test_planner.py

Unit tests for the rule-based Planner.
"""

import unittest

from models.parsed_command import ParsedCommand
from brain.planner import Planner


class TestPlanner(unittest.TestCase):
    """Tests for the Planner class."""

    def setUp(self) -> None:
        """Set up a new Planner instance for each test."""
        self.planner = Planner()

    def test_plan_open_app(self) -> None:
        """Verify a plan to open an application is created correctly."""
        command = ParsedCommand(
            raw_text="open notepad",
            intent="open_app",
            entities={"app_name": "notepad"},
            confidence=1.0,
        )

        plan = self.planner.create_plan(command)

        self.assertEqual(plan.intent, "open_app")
        self.assertEqual(len(plan.steps), 1)
        step = plan.steps[0]
        self.assertEqual(step.action, "open_app")
        self.assertEqual(step.target, "notepad")
        self.assertEqual(step.description, "Open notepad.")

    def test_plan_close_app(self) -> None:
        """Verify a plan to close an application is created correctly."""
        command = ParsedCommand(
            raw_text="close chrome",
            intent="close_app",
            entities={"app": "chrome"},
            confidence=1.0,
        )

        plan = self.planner.create_plan(command)

        self.assertEqual(plan.intent, "close_app")
        self.assertEqual(len(plan.steps), 1)
        step = plan.steps[0]
        self.assertEqual(step.action, "close_app")
        self.assertEqual(step.target, "chrome")
        self.assertEqual(step.description, "Close chrome.")

    def test_plan_unknown_intent(self) -> None:
        """Verify an unknown intent results in an empty plan."""
        command = ParsedCommand(
            raw_text="make me a sandwich",
            intent="unknown",
            confidence=0.0,
        )

        plan = self.planner.create_plan(command)

        self.assertEqual(plan.intent, "unknown")
        self.assertEqual(len(plan.steps), 0)


if __name__ == "__main__":
    unittest.main()