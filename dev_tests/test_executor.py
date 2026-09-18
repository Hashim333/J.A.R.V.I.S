"""
dev_tests/test_executor.py

Unit tests for the Executor and Registry.
"""

import unittest
from typing import Any

from brain.execution_plan import ExecutionPlan, Step
from executor.executor import Executor
from executor.registry import Registry


class MockHandler:
    """A mock handler for testing the Executor's dispatch logic."""

    def __init__(self, should_raise: bool = False, return_value: dict | None = None):
        self.should_raise = should_raise
        self.return_value = return_value or {"success": True, "message": "ok"}
        self.called_with_step = None

    def run(self, step: Step, **kwargs: Any) -> dict:
        self.called_with_step = step
        if self.should_raise:
            raise RuntimeError("Handler failed as requested.")
        return self.return_value


class TestExecutor(unittest.TestCase):
    """Tests for the Executor class."""

    def setUp(self) -> None:
        """Set up a new Registry and Executor for each test."""
        self.registry = Registry()
        self.executor = Executor(self.registry)

    def test_execute_successful_plan(self) -> None:
        """Verify a plan with one successful step returns a success Response."""
        handler = MockHandler()
        self.registry.register("test_action", handler)
        plan = ExecutionPlan(
            raw_text="do test",
            intent="test_intent",
            confidence=1.0,
            steps=[Step(action="test_action", target="test_target")],
        )

        response = self.executor.execute(plan)

        self.assertTrue(response.success)
        self.assertEqual(response.message, "ok")
        self.assertIsNone(response.error)
        self.assertIsNotNone(handler.called_with_step)
        self.assertEqual(handler.called_with_step.target, "test_target")

    def test_execute_stops_on_handler_failure(self) -> None:
        """Verify execution halts if a handler raises an exception."""
        failing_handler = MockHandler(should_raise=True)
        second_handler = MockHandler()
        self.registry.register("failing_action", failing_handler)
        self.registry.register("second_action", second_handler)
        plan = ExecutionPlan(
            raw_text="do two things",
            intent="multi_step",
            confidence=1.0,
            steps=[
                Step(action="failing_action"),
                Step(action="second_action"),
            ],
        )

        response = self.executor.execute(plan)

        self.assertFalse(response.success)
        self.assertEqual(response.message, "I couldn't complete that request.")
        self.assertIn("RuntimeError: Handler failed as requested.", response.error)
        self.assertIsNone(second_handler.called_with_step)  # Second step never ran

    def test_execute_fails_on_unregistered_action(self) -> None:
        """Verify execution fails if an action has no registered handler."""
        plan = ExecutionPlan(
            raw_text="do unknown",
            intent="unknown_intent",
            confidence=1.0,
            steps=[Step(action="unregistered_action")],
        )

        response = self.executor.execute(plan)

        self.assertFalse(response.success)
        self.assertEqual(response.message, "I couldn't complete that request.")
        self.assertIn("KeyError: 'No handler registered for action", response.error)

    def test_execute_empty_plan(self) -> None:
        """Verify an empty plan returns a failed Response with explanation."""
        plan = ExecutionPlan(
            raw_text="do nothing", intent="no_op", confidence=1.0, steps=[]
        )

        response = self.executor.execute(plan)

        self.assertFalse(response.success)
        self.assertEqual(response.message, "I don't know how to do that yet.")

    def test_browser_search_with_none_parameters_does_not_crash_on_get(self) -> None:
        """BrowserHandler treats None parameters as an empty dict."""
        from automation.handlers import BrowserHandler, StepParameterError

        handler = BrowserHandler()

        with self.assertRaisesRegex(StepParameterError, "requires parameter 'query'"):
            handler.run(Step(action="search", parameters=None))



class TestRegistry(unittest.TestCase):
    """Tests for the Registry class."""

    def test_register_and_get_handler(self) -> None:
        """Verify that a registered handler can be retrieved."""
        registry = Registry()
        handler = MockHandler()
        registry.register("my_action", handler)
        self.assertIs(registry.get_handler("my_action"), handler)

    def test_get_unregistered_handler_raises_key_error(self) -> None:
        """Verify getting an unregistered handler raises KeyError."""
        registry = Registry()
        with self.assertRaises(KeyError):
            registry.get_handler("non_existent_action")


if __name__ == "__main__":
    unittest.main()
