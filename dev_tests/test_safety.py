"""
dev_tests/test_safety.py

Tests for the Safety & Confirmation Framework: policy engine, audit log,
validators, and integration with executor and brain.
"""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path

from safety.policy import SafetyPolicy
from safety.audit import AuditLog
from safety.validator import validate_file_path, validate_app_exists, validate_parameters


# =========================================================================
# SafetyPolicy tests
# =========================================================================

class TestSafetyPolicy(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp_dir = tempfile.mkdtemp()
        self.config_path = os.path.join(self.tmp_dir, "safety_config.json")
        self._write_config({})

    def _write_config(self, overrides: dict) -> None:
        config = {
            "speech": {"min_confidence": 0.3, "reject_below": 0.15},
            "confirmation": {
                "required_for": ["shutdown", "restart", "lock", "delete_file"],
                "protected_operations": ["shutdown", "restart", "delete_file"],
            },
            "validation": {"check_file_exists": True, "check_app_exists": True},
            "audit": {"enabled": True, "log_file": os.path.join(self.tmp_dir, "audit.jsonl"), "max_entries": 100},
        }
        config.update(overrides)
        with open(self.config_path, "w") as f:
            json.dump(config, f)

    def _policy(self, overrides: dict = None) -> SafetyPolicy:
        if overrides:
            self._write_config(overrides)
        return SafetyPolicy(self.config_path)

    # --- Speech confidence ---

    def test_high_confidence_accepted(self) -> None:
        policy = self._policy()
        result = policy.check_speech_confidence(0.85)
        self.assertTrue(result["accepted"])
        self.assertNotIn("needs_confirmation", result)

    def test_low_but_acceptable_confidence(self) -> None:
        policy = self._policy()
        result = policy.check_speech_confidence(0.25)
        self.assertTrue(result["accepted"])
        self.assertTrue(result.get("needs_confirmation"))

    def test_rejected_confidence(self) -> None:
        policy = self._policy()
        result = policy.check_speech_confidence(0.05)
        self.assertFalse(result["accepted"])

    def test_custom_thresholds(self) -> None:
        policy = self._policy({"speech": {"min_confidence": 0.5, "reject_below": 0.3}})
        self.assertFalse(policy.check_speech_confidence(0.25)["accepted"])
        self.assertTrue(policy.check_speech_confidence(0.4)["accepted"])
        self.assertTrue(policy.check_speech_confidence(0.6)["accepted"])

    # --- Confirmation ---

    def test_needs_confirmation_for_dangerous(self) -> None:
        policy = self._policy()
        self.assertTrue(policy.needs_confirmation("shutdown"))
        self.assertTrue(policy.needs_confirmation("delete_file"))
        self.assertFalse(policy.needs_confirmation("open_app"))
        self.assertFalse(policy.needs_confirmation("read_screen"))

    def test_is_protected(self) -> None:
        policy = self._policy()
        self.assertTrue(policy.is_protected("shutdown"))
        self.assertTrue(policy.is_protected("delete_file"))
        self.assertFalse(policy.is_protected("lock"))
        self.assertFalse(policy.is_protected("open_app"))

    def test_confirmation_reason(self) -> None:
        policy = self._policy()
        self.assertIn("Shutting down", policy.confirmation_reason("shutdown"))
        self.assertIn("Permanently deleting", policy.confirmation_reason("delete_file"))
        self.assertIn("sleep", policy.confirmation_reason("sleep"))

    # --- Config loading ---

    def test_loads_defaults_when_no_file(self) -> None:
        policy = SafetyPolicy("/nonexistent/path.json")
        self.assertGreater(policy.min_confidence, 0)

    def test_loads_from_file(self) -> None:
        policy = self._policy({"speech": {"min_confidence": 0.7, "reject_below": 0.5}})
        self.assertEqual(policy.min_confidence, 0.7)
        self.assertEqual(policy.reject_below, 0.5)


# =========================================================================
# AuditLog tests
# =========================================================================

class TestAuditLog(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp_dir = tempfile.mkdtemp()
        self.log_path = os.path.join(self.tmp_dir, "audit.jsonl")
        config = {
            "audit": {"enabled": True, "log_file": self.log_path, "max_entries": 100},
        }
        config_path = os.path.join(self.tmp_dir, "config.json")
        with open(config_path, "w") as f:
            json.dump(config, f)
        self.policy = SafetyPolicy(config_path)
        self.audit = AuditLog(self.policy)

    def tearDown(self) -> None:
        if os.path.exists(self.log_path):
            os.unlink(self.log_path)

    def test_record_command(self) -> None:
        self.audit.record_command("shutdown", "shutdown computer", ["shutdown"])
        entries = self.audit.recent_entries(5)
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["type"], "command")
        self.assertEqual(entries[0]["intent"], "shutdown")

    def test_record_confirmation(self) -> None:
        self.audit.record_confirmation("shutdown", True)
        entries = self.audit.recent_entries(5)
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["type"], "confirmation")
        self.assertTrue(entries[0]["granted"])

    def test_record_validation(self) -> None:
        self.audit.record_validation("open_file", False, "File not found")
        entries = self.audit.recent_entries(5)
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["type"], "validation")
        self.assertFalse(entries[0]["passed"])

    def test_record_rejection(self) -> None:
        self.audit.record_rejection("Low confidence", 0.05)
        entries = self.audit.recent_entries(5)
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["type"], "rejection")

    def test_command_history(self) -> None:
        self.audit.record_command("shutdown", "shutdown", ["shutdown"])
        self.audit.record_confirmation("shutdown", True)
        self.audit.record_command("restart", "restart", ["restart"])
        history = self.audit.command_history(5)
        self.assertEqual(len(history), 2)
        self.assertEqual(history[0]["intent"], "shutdown")
        self.assertEqual(history[1]["intent"], "restart")

    def test_clear(self) -> None:
        self.audit.record_command("test", "test", ["test"])
        self.audit.clear()
        self.assertEqual(len(self.audit.recent_entries(5)), 0)

    def test_prune(self) -> None:
        self.audit._max_entries = 3
        for i in range(10):
            self.audit.record_command(f"cmd{i}", f"cmd{i}", [f"cmd{i}"])
        entries = self.audit.recent_entries(10)
        self.assertLessEqual(len(entries), 3)

    def test_disabled_audit(self) -> None:
        config = {"audit": {"enabled": False, "log_file": self.log_path, "max_entries": 100}}
        config_path = os.path.join(self.tmp_dir, "disabled_config.json")
        with open(config_path, "w") as f:
            json.dump(config, f)
        policy = SafetyPolicy(config_path)
        audit = AuditLog(policy)
        audit.record_command("test", "test", ["test"])
        self.assertFalse(os.path.exists(self.log_path))


# =========================================================================
# Validator tests
# =========================================================================

class TestValidator(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp_dir = tempfile.mkdtemp()

    def test_validate_empty_path(self) -> None:
        result = validate_file_path("")
        self.assertFalse(result["valid"])

    def test_validate_valid_file(self) -> None:
        test_file = os.path.join(self.tmp_dir, "test.txt")
        Path(test_file).write_text("hello")
        result = validate_file_path(test_file)
        self.assertTrue(result["valid"])
        self.assertTrue(result["exists"])

    def test_validate_nonexistent_file(self) -> None:
        result = validate_file_path(os.path.join(self.tmp_dir, "nonexistent.txt"))
        self.assertTrue(result["valid"])
        self.assertFalse(result["exists"])

    def test_validate_path_traversal(self) -> None:
        result = validate_file_path("../etc/passwd")
        self.assertFalse(result["valid"])

    def test_validate_windows_path_traversal(self) -> None:
        result = validate_file_path("..\\windows\\system32")
        self.assertFalse(result["valid"])

    def test_validate_parameters_clean(self) -> None:
        result = validate_parameters("open_file", {"path": "/home/test.txt"})
        self.assertTrue(result["valid"])

    def test_validate_parameters_dangerous(self) -> None:
        result = validate_parameters("run", {"command": "format C: /y"})
        self.assertFalse(result["valid"])

    def test_validate_parameters_dangerous_cmd(self) -> None:
        result = validate_parameters("run", {"cmd": "rm -rf /"})
        self.assertFalse(result["valid"])

    def test_app_exists_validation(self) -> None:
        result = validate_app_exists("notepad")
        self.assertTrue(result["valid"])

    def test_app_does_not_exist(self) -> None:
        result = validate_app_exists("XYZZYX_NonExistent_App_12345")
        self.assertTrue(result["valid"])
        self.assertFalse(result["exists"])

    def test_app_empty_name(self) -> None:
        result = validate_app_exists("")
        self.assertFalse(result["valid"])


# =========================================================================
# Integration: Executor safety checks (via mocks)
# =========================================================================

class TestExecutorSafety(unittest.TestCase):
    """Verify the Executor integrates correctly with SafetyPolicy."""

    def setUp(self) -> None:
        self.tmp_dir = tempfile.mkdtemp()
        config = {
            "confirmation": {
                "required_for": ["shutdown", "restart", "delete_file"],
                "protected_operations": ["shutdown", "delete_file"],
            },
            "validation": {"check_file_exists": True, "check_app_exists": True},
            "audit": {"enabled": False, "log_file": "", "max_entries": 0},
        }
        self.config_path = os.path.join(self.tmp_dir, "config.json")
        with open(self.config_path, "w") as f:
            json.dump(config, f)
        self.policy = SafetyPolicy(self.config_path)

    def _make_plan(self, intent: str, action: str, params: dict = None) -> object:
        from brain.execution_plan import ExecutionPlan, Step
        return ExecutionPlan(
            raw_text=f"test {intent}",
            intent=intent,
            confidence=1.0,
            steps=[Step(action=action, target=None, parameters=params or {})],
            metadata={},
        )

    def test_executor_confirms_dangerous_action(self) -> None:
        from executor.executor import Executor
        from executor.registry import Registry
        reg = Registry()
        executor = Executor(reg, safety_policy=self.policy)
        plan = self._make_plan("shutdown", "shutdown")
        response = executor.execute(plan)
        self.assertTrue(response.needs_clarification)
        self.assertIn("Are you sure", response.clarification_question)

    def test_executor_rejects_bad_file_path(self) -> None:
        from executor.executor import Executor
        from executor.registry import Registry
        reg = Registry()
        executor = Executor(reg, safety_policy=self.policy)
        plan = self._make_plan("delete_file", "delete_file",
                               {"file_path": "../etc/passwd"})
        response = executor.execute(plan)
        self.assertFalse(response.success)
        self.assertIn("Path traversal", response.message)

    def test_executor_accepts_safe_action(self) -> None:
        from executor.executor import Executor
        from executor.registry import Registry
        reg = Registry()
        executor = Executor(reg, safety_policy=self.policy)
        # Register a dummy handler for read_screen
        class DummyHandler:
            def run(self, step, **kw):
                return {"success": True, "message": "done"}
        reg.register("read_screen", DummyHandler())
        plan = self._make_plan("read_screen", "read_screen")
        response = executor.execute(plan)
        self.assertTrue(response.success)


if __name__ == "__main__":
    unittest.main()
