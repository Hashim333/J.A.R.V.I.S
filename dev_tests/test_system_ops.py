"""
dev_tests/test_system_ops.py

Tests for the Windows System Manager: parser intents, planner builders,
registry registration, and system_ops module functions.
"""

from __future__ import annotations

import unittest

from brain.parser import Parser
from brain.planner import Planner
from brain.parsed_command import ParsedCommand


# =========================================================================
# Parser tests
# =========================================================================

class TestParserSystemOps(unittest.TestCase):
    """Tests for system operation command parsing."""

    def setUp(self) -> None:
        self.parser = Parser()

    # --- Sign out ---

    def test_sign_out(self) -> None:
        parsed = self.parser.parse("sign out")
        self.assertEqual(parsed.intent, "sign_out")

    def test_log_off(self) -> None:
        parsed = self.parser.parse("log off")
        self.assertEqual(parsed.intent, "sign_out")

    def test_log_out(self) -> None:
        parsed = self.parser.parse("log out")
        self.assertEqual(parsed.intent, "sign_out")

    # --- Cancel shutdown ---

    def test_cancel_shutdown(self) -> None:
        parsed = self.parser.parse("cancel shutdown")
        self.assertEqual(parsed.intent, "cancel_shutdown")

    def test_cancel_restart(self) -> None:
        parsed = self.parser.parse("cancel restart")
        self.assertEqual(parsed.intent, "cancel_shutdown")

    # --- Delayed shutdown ---

    def test_shutdown_in_10_minutes(self) -> None:
        parsed = self.parser.parse("shutdown in 10 minutes")
        self.assertEqual(parsed.intent, "shutdown")
        self.assertEqual(parsed.entities.get("delay_seconds"), 600)

    def test_shutdown_in_5_min(self) -> None:
        parsed = self.parser.parse("shutdown in 5 min")
        self.assertEqual(parsed.intent, "shutdown")
        self.assertEqual(parsed.entities.get("delay_seconds"), 300)

    def test_shutdown_in_1_hour(self) -> None:
        parsed = self.parser.parse("shutdown in 1 hour")
        self.assertEqual(parsed.intent, "shutdown")
        self.assertEqual(parsed.entities.get("delay_seconds"), 3600)

    def test_restart_in_10_minutes(self) -> None:
        parsed = self.parser.parse("restart in 10 minutes")
        self.assertEqual(parsed.intent, "restart")
        self.assertEqual(parsed.entities.get("delay_seconds"), 600)

    def test_restart_my_computer_in_10_minutes(self) -> None:
        parsed = self.parser.parse("restart my computer in 10 minutes")
        self.assertEqual(parsed.intent, "restart")
        self.assertEqual(parsed.entities.get("delay_seconds"), 600)

    def test_immediate_shutdown_still_works(self) -> None:
        parsed = self.parser.parse("shutdown")
        self.assertEqual(parsed.intent, "shutdown")
        self.assertNotIn("delay_seconds", parsed.entities)

    def test_immediate_restart_still_works(self) -> None:
        parsed = self.parser.parse("restart")
        self.assertEqual(parsed.intent, "restart")

    # --- Brightness ---

    def test_set_brightness(self) -> None:
        parsed = self.parser.parse("set brightness to 75")
        self.assertEqual(parsed.intent, "set_brightness")
        self.assertEqual(parsed.entities.get("level"), 75)

    def test_brightness_to_50(self) -> None:
        parsed = self.parser.parse("brightness 50")
        self.assertEqual(parsed.intent, "set_brightness")
        self.assertEqual(parsed.entities.get("level"), 50)

    def test_increase_brightness(self) -> None:
        parsed = self.parser.parse("increase brightness")
        self.assertEqual(parsed.intent, "set_brightness")

    def test_decrease_brightness(self) -> None:
        parsed = self.parser.parse("decrease brightness")
        self.assertEqual(parsed.intent, "set_brightness")

    def test_change_brightness_to_30(self) -> None:
        parsed = self.parser.parse("change brightness to 30")
        self.assertEqual(parsed.intent, "set_brightness")
        self.assertIn("level", parsed.entities)

    # --- WiFi ---

    def test_wifi_on(self) -> None:
        parsed = self.parser.parse("turn on wifi")
        self.assertEqual(parsed.intent, "wifi_on")

    def test_wifi_off(self) -> None:
        parsed = self.parser.parse("turn off wifi")
        self.assertEqual(parsed.intent, "wifi_off")

    def test_enable_wifi(self) -> None:
        parsed = self.parser.parse("enable wifi")
        self.assertEqual(parsed.intent, "wifi_on")

    def test_disable_wifi(self) -> None:
        parsed = self.parser.parse("disable wifi")
        self.assertEqual(parsed.intent, "wifi_off")

    # --- Bluetooth ---

    def test_bluetooth_on(self) -> None:
        parsed = self.parser.parse("turn on bluetooth")
        self.assertEqual(parsed.intent, "bluetooth_on")

    def test_bluetooth_off(self) -> None:
        parsed = self.parser.parse("turn off bluetooth")
        self.assertEqual(parsed.intent, "bluetooth_off")

    def test_enable_bluetooth(self) -> None:
        parsed = self.parser.parse("enable bluetooth")
        self.assertEqual(parsed.intent, "bluetooth_on")

    # --- Airplane mode ---

    def test_airplane_mode_on(self) -> None:
        parsed = self.parser.parse("turn on airplane mode")
        self.assertEqual(parsed.intent, "airplane_mode_on")

    def test_airplane_mode_off(self) -> None:
        parsed = self.parser.parse("turn off airplane mode")
        self.assertEqual(parsed.intent, "airplane_mode_off")

    def test_enable_airplane_mode(self) -> None:
        parsed = self.parser.parse("enable airplane mode")
        self.assertEqual(parsed.intent, "airplane_mode_on")

    # --- System status ---

    def test_battery_status(self) -> None:
        parsed = self.parser.parse("battery status")
        self.assertEqual(parsed.intent, "system_status")
        self.assertEqual(parsed.entities.get("query"), "battery status")

    def test_cpu_usage(self) -> None:
        parsed = self.parser.parse("cpu usage")
        self.assertEqual(parsed.intent, "system_status")
        self.assertEqual(parsed.entities.get("query"), "cpu usage")

    def test_ram_usage(self) -> None:
        parsed = self.parser.parse("ram usage")
        self.assertEqual(parsed.intent, "system_status")

    def test_disk_usage(self) -> None:
        parsed = self.parser.parse("disk usage")
        self.assertEqual(parsed.intent, "system_status")

    def test_network_usage(self) -> None:
        parsed = self.parser.parse("network usage")
        self.assertEqual(parsed.intent, "system_status")

    def test_system_status(self) -> None:
        parsed = self.parser.parse("system status")
        self.assertEqual(parsed.intent, "system_status")
        self.assertEqual(parsed.entities.get("query"), "all")

    def test_whats_using_most_cpu(self) -> None:
        parsed = self.parser.parse("what's using the most cpu")
        self.assertEqual(parsed.intent, "system_status")
        self.assertEqual(parsed.entities.get("query"), "cpu_top")

    # --- System tools ---

    def test_open_task_manager(self) -> None:
        parsed = self.parser.parse("open task manager")
        self.assertEqual(parsed.intent, "open_task_manager")

    def test_task_manager(self) -> None:
        parsed = self.parser.parse("task manager")
        self.assertEqual(parsed.intent, "open_task_manager")

    def test_open_device_manager(self) -> None:
        parsed = self.parser.parse("open device manager")
        self.assertEqual(parsed.intent, "open_device_manager")

    def test_device_manager(self) -> None:
        parsed = self.parser.parse("device manager")
        self.assertEqual(parsed.intent, "open_device_manager")

    def test_open_control_panel(self) -> None:
        parsed = self.parser.parse("open control panel")
        self.assertEqual(parsed.intent, "open_control_panel")

    def test_control_panel(self) -> None:
        parsed = self.parser.parse("control panel")
        self.assertEqual(parsed.intent, "open_control_panel")


# =========================================================================
# Planner tests
# =========================================================================

class TestPlannerSystemOps(unittest.TestCase):
    """Tests for system operation intent builders."""

    def setUp(self) -> None:
        self.planner = Planner()

    def _plan(self, intent: str, entities: dict = None) -> ParsedCommand:
        return ParsedCommand(raw_text="test", intent=intent, entities=entities or {})

    def test_sign_out_plan(self) -> None:
        plan = self.planner.create_plan(self._plan("sign_out"))
        self.assertEqual(plan.steps[0].action, "sign_out")

    def test_cancel_shutdown_plan(self) -> None:
        plan = self.planner.create_plan(self._plan("cancel_shutdown"))
        self.assertEqual(plan.steps[0].action, "cancel_shutdown")

    def test_set_brightness_plan(self) -> None:
        plan = self.planner.create_plan(self._plan("set_brightness", {"level": 75}))
        self.assertEqual(plan.steps[0].action, "set_brightness")
        self.assertEqual(plan.steps[0].parameters["level"], 75)

    def test_wifi_on_plan(self) -> None:
        plan = self.planner.create_plan(self._plan("wifi_on"))
        self.assertEqual(plan.steps[0].action, "wifi_on")

    def test_wifi_off_plan(self) -> None:
        plan = self.planner.create_plan(self._plan("wifi_off"))
        self.assertEqual(plan.steps[0].action, "wifi_off")

    def test_bluetooth_on_plan(self) -> None:
        plan = self.planner.create_plan(self._plan("bluetooth_on"))
        self.assertEqual(plan.steps[0].action, "bluetooth_on")

    def test_bluetooth_off_plan(self) -> None:
        plan = self.planner.create_plan(self._plan("bluetooth_off"))
        self.assertEqual(plan.steps[0].action, "bluetooth_off")

    def test_airplane_mode_on_plan(self) -> None:
        plan = self.planner.create_plan(self._plan("airplane_mode_on"))
        self.assertEqual(plan.steps[0].action, "airplane_mode_on")

    def test_airplane_mode_off_plan(self) -> None:
        plan = self.planner.create_plan(self._plan("airplane_mode_off"))
        self.assertEqual(plan.steps[0].action, "airplane_mode_off")

    def test_system_status_plan(self) -> None:
        plan = self.planner.create_plan(self._plan("system_status", {"query": "cpu"}))
        self.assertEqual(plan.steps[0].action, "system_status")
        self.assertEqual(plan.steps[0].parameters["query"], "cpu")

    def test_open_task_manager_plan(self) -> None:
        plan = self.planner.create_plan(self._plan("open_task_manager"))
        self.assertEqual(plan.steps[0].action, "open_task_manager")

    def test_open_device_manager_plan(self) -> None:
        plan = self.planner.create_plan(self._plan("open_device_manager"))
        self.assertEqual(plan.steps[0].action, "open_device_manager")

    def test_open_control_panel_plan(self) -> None:
        plan = self.planner.create_plan(self._plan("open_control_panel"))
        self.assertEqual(plan.steps[0].action, "open_control_panel")

    def test_delayed_shutdown_plan(self) -> None:
        plan = self.planner.create_plan(self._plan("shutdown", {"delay_seconds": 600}))
        self.assertEqual(plan.steps[0].action, "shutdown")
        self.assertEqual(plan.steps[0].parameters.get("delay_seconds"), 600)

    def test_delayed_restart_plan(self) -> None:
        plan = self.planner.create_plan(self._plan("restart", {"delay_seconds": 300}))
        self.assertEqual(plan.steps[0].action, "restart")
        self.assertEqual(plan.steps[0].parameters.get("delay_seconds"), 300)


# =========================================================================
# Registry integration tests
# =========================================================================

class TestRegistrySystemOps(unittest.TestCase):
    """Verify all system actions are registered."""

    def test_registry_has_system_actions(self) -> None:
        from automation.registry import Registry
        reg = Registry()
        for action in (
            "lock", "shutdown", "restart", "sleep",
            "set_brightness", "wifi_on", "wifi_off",
            "bluetooth_on", "bluetooth_off",
            "airplane_mode_on", "airplane_mode_off",
            "system_status", "sign_out", "cancel_shutdown",
            "open_task_manager", "open_device_manager", "open_control_panel",
        ):
            self.assertTrue(reg.is_registered(action), f"{action} not registered")


# =========================================================================
# system_ops unit tests (no hardware calls)
# =========================================================================

class TestSystemOpsModule(unittest.TestCase):
    """Tests for automation.system_ops that don't require real hardware."""

    def test_open_system_tool_unknown(self) -> None:
        from automation.system_ops import open_system_tool
        result = open_system_tool("nonexistent tool")
        self.assertFalse(result["success"])

    def test_open_system_tool_task_manager(self) -> None:
        from automation.system_ops import open_system_tool
        result = open_system_tool("task manager")
        self.assertTrue(result["success"])

    def test_open_system_tool_device_manager(self) -> None:
        from automation.system_ops import open_system_tool
        result = open_system_tool("device manager")
        self.assertTrue(result["success"])

    def test_open_system_tool_control_panel(self) -> None:
        from automation.system_ops import open_system_tool
        result = open_system_tool("control panel")
        self.assertTrue(result["success"])

    def test_get_cpu_usage_returns_dict(self) -> None:
        from automation.system_ops import get_cpu_usage
        result = get_cpu_usage()
        self.assertTrue(result["success"])
        self.assertIn("cpu_percent", result)

    def test_get_ram_usage_returns_dict(self) -> None:
        from automation.system_ops import get_ram_usage
        result = get_ram_usage()
        self.assertTrue(result["success"])
        self.assertIn("ram_percent", result)

    def test_get_disk_usage_returns_dict(self) -> None:
        from automation.system_ops import get_disk_usage
        result = get_disk_usage()
        self.assertTrue(result["success"])
        self.assertIn("disks", result)

    def test_get_network_usage_returns_dict(self) -> None:
        from automation.system_ops import get_network_usage
        result = get_network_usage()
        self.assertTrue(result["success"])
        self.assertIn("sent_mb", result)

    def test_get_top_cpu_processes_returns_dict(self) -> None:
        from automation.system_ops import get_top_cpu_processes
        result = get_top_cpu_processes(limit=3)
        self.assertTrue(result["success"])
        self.assertIn("processes", result)

    def test_delayed_shutdown_seconds_param(self) -> None:
        """Verify the function accepts seconds parameter correctly."""
        from automation.system_ops import delayed_shutdown, delayed_restart, cancel_delayed_shutdown
        # We can't actually test shutdown, but we can verify the function
        # signature and that it doesn't crash when called with seconds.
        # These would fail without admin rights but should not crash.
        result = delayed_shutdown(seconds=999999)
        self.assertIn("success", result)

    def test_cancel_delayed_shutdown_returns_dict(self) -> None:
        from automation.system_ops import cancel_delayed_shutdown
        result = cancel_delayed_shutdown()
        self.assertIn("success", result)


if __name__ == "__main__":
    unittest.main()
