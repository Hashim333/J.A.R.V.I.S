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
            entities={"app_name": "chrome"},
            confidence=1.0,
        )

        plan = self.planner.create_plan(command)

        self.assertEqual(plan.intent, "close_app")
        self.assertEqual(len(plan.steps), 1)
        step = plan.steps[0]
        self.assertEqual(step.action, "close_app")
        self.assertEqual(step.target, "chrome")
        self.assertEqual(step.description, "Close chrome.")

    def test_plan_open_app_with_profile(self) -> None:
        """Verify a plan to open chrome with a profile passes the profile param."""
        command = ParsedCommand(
            raw_text="open chrome with profile work",
            intent="open_app",
            entities={"app_name": "chrome", "profile": "work"},
            confidence=1.0,
        )

        plan = self.planner.create_plan(command)

        self.assertEqual(plan.intent, "open_app")
        self.assertEqual(len(plan.steps), 1)
        step = plan.steps[0]
        self.assertEqual(step.action, "open_app")
        self.assertEqual(step.target, "chrome")
        self.assertEqual(step.parameters.get("profile"), "work")
        self.assertEqual(step.description, "Open chrome with profile 'work'.")

    def test_plan_restart_app(self) -> None:
        """Verify a plan to restart an application is created correctly."""
        command = ParsedCommand(
            raw_text="restart chrome",
            intent="restart_app",
            entities={"app_name": "chrome"},
            confidence=1.0,
        )
        plan = self.planner.create_plan(command)
        self.assertEqual(plan.intent, "restart_app")
        self.assertEqual(len(plan.steps), 1)
        step = plan.steps[0]
        self.assertEqual(step.action, "restart_app")
        self.assertEqual(step.target, "chrome")

    def test_plan_minimize_app(self) -> None:
        """Verify a plan to minimize an application is created correctly."""
        command = ParsedCommand(
            raw_text="minimize chrome",
            intent="minimize_app",
            entities={"app_name": "chrome"},
            confidence=1.0,
        )
        plan = self.planner.create_plan(command)
        self.assertEqual(plan.intent, "minimize_app")
        self.assertEqual(len(plan.steps), 1)
        step = plan.steps[0]
        self.assertEqual(step.action, "minimize_app")
        self.assertEqual(step.target, "chrome")

    def test_plan_maximize_app(self) -> None:
        """Verify a plan to maximize an application is created correctly."""
        command = ParsedCommand(
            raw_text="maximize chrome",
            intent="maximize_app",
            entities={"app_name": "chrome"},
            confidence=1.0,
        )
        plan = self.planner.create_plan(command)
        self.assertEqual(plan.intent, "maximize_app")
        self.assertEqual(len(plan.steps), 1)
        step = plan.steps[0]
        self.assertEqual(step.action, "maximize_app")
        self.assertEqual(step.target, "chrome")

    def test_plan_close_all_apps(self) -> None:
        """Verify a plan to close all applications is created correctly."""
        command = ParsedCommand(
            raw_text="close everything",
            intent="close_all_apps",
            confidence=1.0,
        )
        plan = self.planner.create_plan(command)
        self.assertEqual(plan.intent, "close_all_apps")
        self.assertEqual(len(plan.steps), 1)
        step = plan.steps[0]
        self.assertEqual(step.action, "close_all_apps")
        self.assertIsNone(step.target)

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