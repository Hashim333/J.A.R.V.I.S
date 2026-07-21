"""
dev_tests/test_security_tools.py

Tests for the Ethical Hacking Toolkit: parser intents, planner builders,
registry registration, and security_tools module functions.
"""

from __future__ import annotations

import os
import tempfile
import unittest

from brain.parser import Parser
from brain.planner import Planner
from brain.parsed_command import ParsedCommand


# =========================================================================
# Parser tests
# =========================================================================

class TestParserSecurity(unittest.TestCase):
    """Tests for security/pentest command parsing."""

    def setUp(self) -> None:
        self.parser = Parser()

    def test_create_pentest_report(self) -> None:
        parsed = self.parser.parse("create pentest report")
        self.assertEqual(parsed.intent, "create_pentest_report")

    def test_create_report(self) -> None:
        parsed = self.parser.parse("create report")
        self.assertEqual(parsed.intent, "create_pentest_report")

    def test_generate_pentest_report(self) -> None:
        parsed = self.parser.parse("generate pentest report")
        self.assertEqual(parsed.intent, "create_pentest_report")

    def test_create_penetration_test_report(self) -> None:
        parsed = self.parser.parse("create penetration test report")
        self.assertEqual(parsed.intent, "create_pentest_report")

    def test_organize_scan_results(self) -> None:
        parsed = self.parser.parse("organize scan results")
        self.assertEqual(parsed.intent, "organize_scan_results")

    def test_organize_scan_results_to_project(self) -> None:
        parsed = self.parser.parse("organize scan results to project x")
        self.assertEqual(parsed.intent, "organize_scan_results")
        self.assertEqual(parsed.entities.get("project_name"), "project x")

    def test_summarize_scan_results(self) -> None:
        parsed = self.parser.parse("summarize scan results")
        self.assertEqual(parsed.intent, "summarize_scan_results")

    def test_summarize_scan_results_with_file(self) -> None:
        parsed = self.parser.parse("summarize scan results /tmp/scan.nmap")
        self.assertEqual(parsed.intent, "summarize_scan_results")
        self.assertEqual(parsed.entities.get("file_path"), "/tmp/scan.nmap")

    def test_create_pentest_project(self) -> None:
        parsed = self.parser.parse("create pentest project client-x")
        self.assertEqual(parsed.intent, "create_pentest_project")
        self.assertEqual(parsed.entities.get("project_name"), "client-x")

    def test_new_pentest_project(self) -> None:
        parsed = self.parser.parse("new pentest project")
        self.assertEqual(parsed.intent, "create_pentest_project")

    def test_setup_pentest_project(self) -> None:
        parsed = self.parser.parse("setup pentest project")
        self.assertEqual(parsed.intent, "create_pentest_project")

    def test_open_wireshark(self) -> None:
        """Security tool launching goes through the existing app flow."""
        parsed = self.parser.parse("open wireshark")
        self.assertEqual(parsed.intent, "open_app")


# =========================================================================
# Planner tests
# =========================================================================

class TestPlannerSecurity(unittest.TestCase):
    """Tests for security intent builders."""

    def setUp(self) -> None:
        self.planner = Planner()

    def _plan(self, intent: str, entities: dict = None) -> ParsedCommand:
        return ParsedCommand(raw_text="test", intent=intent, entities=entities or {})

    def test_create_pentest_report_plan(self) -> None:
        plan = self.planner.create_plan(self._plan("create_pentest_report", {"client_name": "Acme"}))
        self.assertEqual(plan.steps[0].action, "create_pentest_report")
        self.assertEqual(plan.steps[0].parameters.get("client_name"), "Acme")

    def test_organize_scan_results_plan(self) -> None:
        plan = self.planner.create_plan(self._plan("organize_scan_results", {"project_name": "project-x"}))
        self.assertEqual(plan.steps[0].action, "organize_scan_results")

    def test_summarize_scan_results_plan(self) -> None:
        plan = self.planner.create_plan(self._plan("summarize_scan_results", {"file_path": "/tmp/scan.xml"}))
        self.assertEqual(plan.steps[0].action, "summarize_scan_results")

    def test_create_pentest_project_plan(self) -> None:
        plan = self.planner.create_plan(self._plan("create_pentest_project", {"project_name": "client-x"}))
        self.assertEqual(plan.steps[0].action, "create_pentest_project")


# =========================================================================
# Registry tests
# =========================================================================

class TestRegistrySecurity(unittest.TestCase):
    """Verify all security actions are registered."""

    def test_registry_has_security_actions(self) -> None:
        from automation.registry import Registry
        reg = Registry()
        for action in (
            "create_pentest_report",
            "organize_scan_results",
            "summarize_scan_results",
            "create_pentest_project",
        ):
            self.assertTrue(reg.is_registered(action), f"{action} not registered")


# =========================================================================
# security_tools module tests
# =========================================================================

class TestSecurityToolsModule(unittest.TestCase):
    """Tests for automation.security_tools."""

    def setUp(self) -> None:
        self.tmp_dir = tempfile.mkdtemp()

    def tearDown(self) -> None:
        import shutil
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    def test_create_project_structure(self) -> None:
        from automation.security_tools import create_project_structure
        result = create_project_structure("test-project", base_dir=self.tmp_dir)
        self.assertTrue(result["success"])
        root = os.path.join(self.tmp_dir, "test-project")
        self.assertTrue(os.path.isdir(os.path.join(root, "01-Reconnaissance", "nmap")))
        self.assertTrue(os.path.isdir(os.path.join(root, "02-Exploitation")))
        self.assertTrue(os.path.isdir(os.path.join(root, "05-Reporting", "findings")))

    def test_create_pentest_report(self) -> None:
        from automation.security_tools import create_pentest_report
        result = create_pentest_report("Acme Corp", "pentest-2026", output_dir=self.tmp_dir)
        self.assertTrue(result["success"])
        report_path = os.path.join(self.tmp_dir, "pentest-2026_Pentest_Report.md")
        self.assertTrue(os.path.exists(report_path))
        content = open(report_path, encoding="utf-8").read()
        self.assertIn("Acme Corp", content)
        self.assertIn("pentest-2026", content)

    def test_organize_scan_results_no_files(self) -> None:
        from automation.security_tools import organize_scan_results
        empty_dir = os.path.join(self.tmp_dir, "empty")
        os.makedirs(empty_dir)
        result = organize_scan_results(empty_dir, "test-project", base_dir=self.tmp_dir)
        self.assertTrue(result["success"])

    def test_organize_scan_results_with_files(self) -> None:
        from automation.security_tools import organize_scan_results
        src = os.path.join(self.tmp_dir, "scans")
        os.makedirs(src)
        for fname in ("scan.xml", "result.nmap", "output.txt"):
            open(os.path.join(src, fname), "w").close()
        result = organize_scan_results(src, "test-project", base_dir=self.tmp_dir)
        self.assertTrue(result["success"])
        self.assertGreater(result["details"]["count"], 0)

    def test_summarize_nmap_normal_output(self) -> None:
        from automation.security_tools import summarize_scan_results
        scan_file = os.path.join(self.tmp_dir, "scan.nmap")
        with open(scan_file, "w") as f:
            f.write("Nmap scan report for 192.168.1.1\n")
            f.write("22/tcp   open  ssh\n")
            f.write("80/tcp   open  http\n")
            f.write("Nmap scan report for 192.168.1.2 (192.168.1.2)\n")
            f.write("443/tcp  open  https\n")
        result = summarize_scan_results(scan_file)
        self.assertTrue(result["success"])
        self.assertIn("hosts_scanned", result["details"])

    def test_summarize_xml_nmap(self) -> None:
        from automation.security_tools import summarize_scan_results
        scan_file = os.path.join(self.tmp_dir, "scan.xml")
        with open(scan_file, "w") as f:
            f.write('<?xml version="1.0"?>\n<nmaprun>\n')
            f.write('<host><address addr="10.0.0.1"/>\n')
            f.write('<ports><port portid="22"><state state="open"/><service name="ssh"/></port></ports>\n')
            f.write('</host>\n</nmaprun>\n')
        result = summarize_scan_results(scan_file)
        self.assertTrue(result["success"])
        self.assertEqual(result["details"].get("type"), "nmap_xml")

    def test_summarize_gnmap(self) -> None:
        from automation.security_tools import summarize_scan_results
        scan_file = os.path.join(self.tmp_dir, "scan.gnmap")
        with open(scan_file, "w") as f:
            f.write("Host: 10.0.0.1 ()    Ports: 22/open/tcp//ssh///\n")
            f.write("Host: 10.0.0.2 ()    Ports: 80/open/tcp//http///\n")
        result = summarize_scan_results(scan_file)
        self.assertTrue(result["success"])
        self.assertEqual(result["details"].get("type"), "nmap_gnmap")

    def test_summarize_generic_text(self) -> None:
        from automation.security_tools import summarize_scan_results
        scan_file = os.path.join(self.tmp_dir, "output.txt")
        with open(scan_file, "w") as f:
            f.write("192.168.1.1:22\n192.168.1.1:80\n10.0.0.1:443\n")
        result = summarize_scan_results(scan_file)
        self.assertTrue(result["success"])
        self.assertIn("unique_ips", result["details"])

    def test_summarize_file_not_found(self) -> None:
        from automation.security_tools import summarize_scan_results
        result = summarize_scan_results("/nonexistent/file.txt")
        self.assertFalse(result["success"])

    def test_open_tool_documentation_known(self) -> None:
        from automation.security_tools import open_tool_documentation
        result = open_tool_documentation("nmap")
        self.assertTrue(result["success"])

    def test_open_tool_documentation_unknown(self) -> None:
        from automation.security_tools import open_tool_documentation
        result = open_tool_documentation("nonexistent-tool")
        self.assertFalse(result["success"])

    def test_tool_launch_alias_exists(self) -> None:
        from automation.application_registry import _WELL_KNOWN_ALIASES, _SYSTEM_APPS
        self.assertIn("nmap", _WELL_KNOWN_ALIASES)
        self.assertIn("wireshark", _WELL_KNOWN_ALIASES)
        self.assertIn("burp", _WELL_KNOWN_ALIASES)
        self.assertIn("metasploit", _WELL_KNOWN_ALIASES)
        self.assertIn("nmap", _SYSTEM_APPS)
        self.assertIn("wireshark", _SYSTEM_APPS)


if __name__ == "__main__":
    unittest.main()
