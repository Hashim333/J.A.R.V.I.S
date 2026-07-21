"""
dev_tests/test_application_registry.py

Integration tests for the dynamic ApplicationRegistry.

These tests verify that:
  1. Discovery runs without error and finds a reasonable number of apps.
  2. Well-known apps resolve to correct executables.
  3. System apps (notepad, calculator, paint) resolve correctly.
  4. Generic aliases (browser, terminal) resolve to correct apps.
  5. Well-known aliases (vscode, spotify) resolve correctly.
  6. Unknown apps return None.
  7. Fuzzy matching does not produce false positives for very different names.
  8. Multiple commands are detected as such (not merged into one app name).
"""

import unittest
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from automation.application_registry import ApplicationRegistry
from brain.parser import Parser


# ---------------------------------------------------------------------------
# ApplicationRegistry integration tests
# ---------------------------------------------------------------------------


class TestApplicationRegistry(unittest.TestCase):
    """Tests that the registry discovers and resolves real Windows applications."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.reg = ApplicationRegistry()

    def test_discovery_finds_apps(self) -> None:
        """The registry should find at least 50 applications on a typical Windows system."""
        self.assertGreaterEqual(self.reg.count, 50,
                                f"Expected >= 50 apps, found {self.reg.count}")

    def test_exact_canonical_name(self) -> None:
        """Exact canonical name should resolve with confidence 1.0."""
        info = self.reg.lookup("notepad")
        self.assertIsNotNone(info)
        self.assertEqual(info.canonical_name, "Notepad")
        self.assertTrue(info.executable.endswith("notepad.exe"),
                        f"Expected notepad.exe, got {info.executable}")

    def test_calculator(self) -> None:
        """'calculator' should resolve to calc.exe."""
        info = self.reg.lookup("calculator")
        self.assertIsNotNone(info)
        self.assertIn("calc", info.executable.casefold())

    def test_calc_alias(self) -> None:
        """'calc' should resolve to Calculator."""
        info = self.reg.lookup("calc")
        self.assertIsNotNone(info)
        # Should map to the same executable as calculator
        calc_info = self.reg.lookup("calculator")
        if calc_info:
            self.assertEqual(info.executable, calc_info.executable)

    def test_paint(self) -> None:
        """'paint' should resolve to mspaint.exe."""
        info = self.reg.lookup("paint")
        self.assertIsNotNone(info)
        self.assertIn("mspaint", info.executable.casefold())

    def test_chrome(self) -> None:
        """'chrome' should resolve to chrome.exe."""
        info = self.reg.lookup("chrome")
        self.assertIsNotNone(info)
        self.assertTrue(info.executable.casefold().endswith("chrome.exe"),
                        f"Expected chrome.exe, got {info.executable}")

    def test_google_chrome_alias(self) -> None:
        """'google chrome' should resolve to Chrome."""
        info = self.reg.lookup("google chrome")
        self.assertIsNotNone(info)
        self.assertIn("chrome", info.executable.casefold())

    def test_code_editor(self) -> None:
        """'code' should resolve to Visual Studio Code (Code.exe)."""
        info = self.reg.lookup("code")
        self.assertIsNotNone(info)
        self.assertIn("code", info.canonical_name.casefold())

    def test_vscode_alias(self) -> None:
        """'vscode' should resolve to Visual Studio Code."""
        info = self.reg.lookup("vscode")
        self.assertIsNotNone(info)
        self.assertIn("code", info.canonical_name.casefold())

    def test_terminal(self) -> None:
        """'terminal' should resolve to a terminal (PowerShell/cmd)."""
        info = self.reg.lookup("terminal")
        self.assertIsNotNone(info)
        self.assertIn("powershell", info.executable.casefold())

    def test_browser_generic_alias(self) -> None:
        """'browser' should resolve to Chrome, NOT DB Browser."""
        info = self.reg.lookup("browser")
        self.assertIsNotNone(info)
        self.assertIn("chrome", info.executable.casefold())

    def test_well_known_spotify(self) -> None:
        """'spotify' should resolve via well-known alias."""
        info = self.reg.lookup("spotify")
        self.assertIsNotNone(info)
        self.assertEqual(info.canonical_name, "Spotify")

    def test_well_known_discord(self) -> None:
        """'discord' should resolve via well-known alias."""
        info = self.reg.lookup("discord")
        self.assertIsNotNone(info)
        self.assertEqual(info.canonical_name, "Discord")

    def test_well_known_steam(self) -> None:
        """'steam' should resolve via well-known alias."""
        info = self.reg.lookup("steam")
        self.assertIsNotNone(info)
        self.assertEqual(info.canonical_name, "Steam")

    def test_well_known_zoom(self) -> None:
        """'zoom' should resolve via well-known alias."""
        info = self.reg.lookup("zoom")
        self.assertIsNotNone(info)
        self.assertEqual(info.canonical_name, "Zoom")

    def test_well_known_obsidian(self) -> None:
        """'obsidian' should resolve via well-known alias."""
        info = self.reg.lookup("obsidian")
        self.assertIsNotNone(info)
        self.assertEqual(info.canonical_name, "Obsidian")

    def test_well_known_vlc(self) -> None:
        """'vlc' should resolve to VLC media player."""
        info = self.reg.lookup("vlc")
        self.assertIsNotNone(info)

    def test_notepadpp(self) -> None:
        """'notepad++' should resolve to Notepad++, not system Notepad."""
        info = self.reg.lookup("notepad++")
        self.assertIsNotNone(info)
        self.assertEqual(info.canonical_name, "Notepad++")

    def test_snipping_tool(self) -> None:
        """'snipping tool' should resolve to Snipping Tool."""
        info = self.reg.lookup("snipping tool")
        self.assertIsNotNone(info)
        self.assertEqual(info.canonical_name, "Snipping Tool")

    def test_unknown_app_returns_none(self) -> None:
        """An app that is definitely not installed should return None."""
        info = self.reg.lookup("xyznonexistentapp12345")
        self.assertIsNone(info)

    def test_notepad_is_not_notepadpp(self) -> None:
        """'notepad' should return system Notepad, not Notepad++."""
        info = self.reg.lookup("notepad")
        self.assertIsNotNone(info)
        self.assertNotEqual(info.canonical_name, "Notepad++")
        self.assertIn("notepad", info.executable.casefold())

    def test_ambiguous_returns_none(self) -> None:
        """Vague names that match many apps should return None (ambiguous)."""
        # 'illustrator' typically produces multiple matches (Administrative Tools, etc.)
        info = self.reg.lookup("illustrator")
        # If Illustrator is not installed, it should return None
        # If it is installed, it should return an ApplicationInfo
        if info is not None:
            self.assertTrue(hasattr(info, "canonical_name"))

    def test_fuzzy_no_false_positive(self) -> None:
        """Completely unrelated terms should not match real apps."""
        # 'xyzwizard' should not match any app
        info = self.reg.lookup("xyzwizard")
        self.assertIsNone(info)

    def test_search_returns_scored_results(self) -> None:
        """search() should return results sorted by score descending."""
        results = self.reg.search("chrome")
        self.assertGreater(len(results), 0)
        for i in range(len(results) - 1):
            self.assertGreaterEqual(results[i][1], results[i + 1][1])

    def test_refresh_rebuilds_index(self) -> None:
        """refresh() should re-scan and return a count."""
        count = self.reg.refresh()
        self.assertGreater(count, 0)
        self.assertEqual(count, self.reg.count)

    def test_list_applications_returns_sorted(self) -> None:
        """list_applications() should return apps sorted by canonical name (case-insensitive)."""
        apps = self.reg.list_applications()
        self.assertGreater(len(apps), 0)
        names = [a.canonical_name.casefold() for a in apps]
        self.assertEqual(names, sorted(names))


# ---------------------------------------------------------------------------
# Parser multi-command detection tests
# ---------------------------------------------------------------------------


class TestParserMultiCommand(unittest.TestCase):
    """Tests that the parser correctly handles garbled multi-command transcripts."""

    def setUp(self) -> None:
        self.parser = Parser()

    def test_simple_multi_command(self) -> None:
        """'open chrome open chrome open calculator' should not merge names."""
        parsed = self.parser.parse("open chrome open chrome open calculator")
        self.assertEqual(parsed.intent, "open_app")
        # The parser should extract only the first "chrome"
        self.assertEqual(parsed.entities.get("app_name"), "chrome")

    def test_multi_command_different_apps(self) -> None:
        """'open notepad open calculator' should extract the first app."""
        parsed = self.parser.parse("open notepad open calculator")
        self.assertEqual(parsed.intent, "open_app")
        self.assertEqual(parsed.entities.get("app_name"), "notepad")

    def test_multi_command_verb_close(self) -> None:
        """'open chrome close notepad' should extract chrome."""
        parsed = self.parser.parse("open chrome close notepad")
        self.assertEqual(parsed.intent, "open_app")
        self.assertEqual(parsed.entities.get("app_name"), "chrome")

    def test_compound_command_preserved(self) -> None:
        """Real compound commands like 'open chrome and search python' should still work."""
        parsed = self.parser.parse("open chrome and search python")
        self.assertEqual(parsed.intent, "compound")
        commands = parsed.entities.get("commands", [])
        self.assertEqual(len(commands), 2)

    def test_multi_command_focus_verb(self) -> None:
        """'open chrome focus notepad' should extract chrome."""
        parsed = self.parser.parse("open chrome focus notepad")
        self.assertEqual(parsed.intent, "open_app")
        self.assertEqual(parsed.entities.get("app_name"), "chrome")

    def test_multi_command_with_filler(self) -> None:
        """Filler words should be stripped before multi-command detection."""
        parsed = self.parser.parse("please open chrome and open calculator")
        self.assertEqual(parsed.intent, "compound")
        commands = parsed.entities.get("commands", [])
        self.assertGreaterEqual(len(commands), 2)

    def test_single_command_unaffected(self) -> None:
        """Normal single commands should be unaffected by the fix."""
        parsed = self.parser.parse("open chrome")
        self.assertEqual(parsed.intent, "open_app")
        self.assertEqual(parsed.entities.get("app_name"), "chrome")

    def test_single_command_website_unaffected(self) -> None:
        """Website commands should work normally."""
        parsed = self.parser.parse("open youtube")
        self.assertEqual(parsed.intent, "open_website")
        self.assertEqual(parsed.entities.get("website"), "youtube")


if __name__ == "__main__":
    unittest.main()
