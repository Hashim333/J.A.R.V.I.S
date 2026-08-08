"""
tests/test_confirmation.py — Unit tests for ConfirmationEngine, parser
improvements, pipeline confirmation flow, and natural language phrasings.
"""

from __future__ import annotations

from unittest import TestCase

from thinking.confirmation import ConfirmationEngine
from brain.parser import Parser


# ======================================================================
#  Part 1 — ConfirmationEngine
# ======================================================================

class TestConfirmationEngineBuild(TestCase):
    def setUp(self) -> None:
        self.ce = ConfirmationEngine()

    def test_close_app(self) -> None:
        q = self.ce.build_question("close_app", {"app_name": "notepad"})
        self.assertEqual(q, "Are you sure you want me to close notepad?")

    def test_close_app_no_name(self) -> None:
        q = self.ce.build_question("close_app", {})
        self.assertEqual(q, "Are you sure you want me to close this application?")

    def test_shutdown_windows(self) -> None:
        q = self.ce.build_question("shutdown_windows", {})
        self.assertEqual(q, "Are you sure you want me to shut down your computer?")

    def test_shutdown_windows_with_delay(self) -> None:
        q = self.ce.build_question("shutdown_windows", {"delay_seconds": 120})
        self.assertEqual(q, "Are you sure you want me to shut down your computer in 2 minutes?")

    def test_shutdown_windows_single_minute(self) -> None:
        q = self.ce.build_question("shutdown_windows", {"delay_seconds": 60})
        self.assertEqual(q, "Are you sure you want me to shut down your computer in 1 minute?")

    def test_restart(self) -> None:
        q = self.ce.build_question("restart", {})
        self.assertEqual(q, "Are you sure you want me to restart your computer?")

    def test_close_jarvis(self) -> None:
        q = self.ce.build_question("close_jarvis", {})
        self.assertEqual(q, "Are you sure you want me to shut down? I will stop listening and close.")

    def test_delete_file(self) -> None:
        q = self.ce.build_question("delete_file", {"file_query": "Downloads"})
        self.assertEqual(q, "This will permanently delete Downloads. Continue?")

    def test_format_drive(self) -> None:
        q = self.ce.build_question("format_drive", {"drive": "D"})
        self.assertEqual(q, "This will erase all data on drive D. Are you sure?")

    def test_kill_process(self) -> None:
        q = self.ce.build_question("kill_process", {"process": "chrome"})
        self.assertEqual(q, "Are you sure you want me to terminate chrome?")

    def test_close_all_apps(self) -> None:
        q = self.ce.build_question("close_all_apps", {})
        self.assertEqual(q, "Are you sure you want me to close all open applications?")

    def test_generic_fallback(self) -> None:
        q = self.ce.build_question("unknown_intent", {})
        self.assertEqual(q, "Are you sure you want me to do that?")


class TestConfirmationEngineClassify(TestCase):
    def setUp(self) -> None:
        self.ce = ConfirmationEngine()

    def test_affirmative_yes(self) -> None:
        self.assertEqual(self.ce.classify_answer("yes"), "affirmative")

    def test_affirmative_yep(self) -> None:
        self.assertEqual(self.ce.classify_answer("yep"), "affirmative")

    def test_affirmative_yeah(self) -> None:
        self.assertEqual(self.ce.classify_answer("yeah"), "affirmative")

    def test_affirmative_sure(self) -> None:
        self.assertEqual(self.ce.classify_answer("sure"), "affirmative")

    def test_affirmative_proceed(self) -> None:
        self.assertEqual(self.ce.classify_answer("proceed"), "affirmative")

    def test_affirmative_do_it(self) -> None:
        self.assertEqual(self.ce.classify_answer("do it"), "affirmative")

    def test_affirmative_go_ahead(self) -> None:
        self.assertEqual(self.ce.classify_answer("go ahead"), "affirmative")

    def test_affirmative_confirm(self) -> None:
        self.assertEqual(self.ce.classify_answer("confirm"), "affirmative")

    def test_affirmative_absolutely(self) -> None:
        self.assertEqual(self.ce.classify_answer("absolutely"), "affirmative")

    def test_negative_no(self) -> None:
        self.assertEqual(self.ce.classify_answer("no"), "negative")

    def test_negative_cancel(self) -> None:
        self.assertEqual(self.ce.classify_answer("cancel"), "negative")

    def test_negative_stop(self) -> None:
        self.assertEqual(self.ce.classify_answer("stop"), "negative")

    def test_negative_never_mind(self) -> None:
        self.assertEqual(self.ce.classify_answer("never mind"), "negative")

    def test_negative_dont(self) -> None:
        self.assertEqual(self.ce.classify_answer("don't"), "negative")

    def test_negative_no_thanks(self) -> None:
        self.assertEqual(self.ce.classify_answer("no thanks"), "negative")

    def test_negative_nope(self) -> None:
        self.assertEqual(self.ce.classify_answer("nope"), "negative")

    def test_affirmative_with_extra_words(self) -> None:
        self.assertEqual(self.ce.classify_answer("yes please"), "affirmative")

    def test_negative_with_extra_words(self) -> None:
        self.assertEqual(self.ce.classify_answer("no I don't think so"), "negative")

    def test_unknown_answer(self) -> None:
        self.assertEqual(self.ce.classify_answer("maybe"), "unknown")

    def test_unknown_gibberish(self) -> None:
        self.assertEqual(self.ce.classify_answer("asdf1234"), "unknown")

    def test_empty_string(self) -> None:
        self.assertEqual(self.ce.classify_answer(""), "unknown")

    def test_affirmative_case_insensitive(self) -> None:
        self.assertEqual(self.ce.classify_answer("YEAH"), "affirmative")

    def test_affirmative_mixed_case(self) -> None:
        self.assertEqual(self.ce.classify_answer("Go Ahead"), "affirmative")


# ======================================================================
#  Part 3 — Parser natural language phrasings
# ======================================================================

class TestParserOpenApp(TestCase):
    """Verify multiple ways to express opening applications."""

    def setUp(self) -> None:
        self.parser = Parser()

    def test_open_chrome(self) -> None:
        result = self.parser.parse("open chrome")
        self.assertEqual(result.intent, "open_app")
        self.assertEqual(result.entities.get("app_name"), "chrome")

    def test_launch_chrome(self) -> None:
        result = self.parser.parse("launch chrome")
        self.assertEqual(result.intent, "open_app")
        self.assertEqual(result.entities.get("app_name"), "chrome")

    def test_start_chrome(self) -> None:
        result = self.parser.parse("start chrome")
        self.assertEqual(result.intent, "open_app")
        self.assertEqual(result.entities.get("app_name"), "chrome")

    def test_run_chrome(self) -> None:
        result = self.parser.parse("run chrome")
        self.assertEqual(result.intent, "open_app")
        self.assertEqual(result.entities.get("app_name"), "chrome")

    def test_can_you_open_chrome(self) -> None:
        result = self.parser.parse("can you open chrome")
        self.assertEqual(result.intent, "open_app")
        self.assertEqual(result.entities.get("app_name"), "chrome")

    def test_please_launch_chrome(self) -> None:
        result = self.parser.parse("please launch chrome")
        self.assertEqual(result.intent, "open_app")
        self.assertEqual(result.entities.get("app_name"), "chrome")

    def test_i_need_chrome(self) -> None:
        result = self.parser.parse("i need chrome")
        self.assertEqual(result.intent, "open_app")
        self.assertEqual(result.entities.get("app_name"), "chrome")

    def test_open_notepad(self) -> None:
        result = self.parser.parse("open notepad")
        self.assertEqual(result.intent, "open_app")
        self.assertEqual(result.entities.get("app_name"), "notepad")


class TestParserCloseApp(TestCase):
    """Verify multiple ways to express closing applications."""

    def setUp(self) -> None:
        self.parser = Parser()

    def test_close_chrome(self) -> None:
        result = self.parser.parse("close chrome")
        self.assertEqual(result.intent, "close_app")
        self.assertEqual(result.entities.get("app_name"), "chrome")

    def test_exit_chrome(self) -> None:
        result = self.parser.parse("exit chrome")
        self.assertEqual(result.intent, "close_app")
        self.assertEqual(result.entities.get("app_name"), "chrome")

    def test_quit_chrome(self) -> None:
        result = self.parser.parse("quit chrome")
        self.assertEqual(result.intent, "close_app")
        self.assertEqual(result.entities.get("app_name"), "chrome")

    def test_terminate_chrome(self) -> None:
        result = self.parser.parse("terminate chrome")
        self.assertEqual(result.intent, "close_app")
        self.assertEqual(result.entities.get("app_name"), "chrome")

    def test_kill_chrome(self) -> None:
        result = self.parser.parse("kill chrome")
        self.assertEqual(result.intent, "close_app")
        self.assertEqual(result.entities.get("app_name"), "chrome")

    def test_close_this_application(self) -> None:
        result = self.parser.parse("close this application")
        self.assertEqual(result.intent, "close_app")
        self.assertTrue(result.entities.get("needs_context"))


class TestParserCloseJarvis(TestCase):
    def setUp(self) -> None:
        self.parser = Parser()

    def test_shutdown_jarvis(self) -> None:
        result = self.parser.parse("shutdown jarvis")
        self.assertEqual(result.intent, "close_jarvis")

    def test_close_jarvis(self) -> None:
        result = self.parser.parse("close jarvis")
        self.assertEqual(result.intent, "close_jarvis")

    def test_exit_jarvis(self) -> None:
        result = self.parser.parse("exit jarvis")
        self.assertEqual(result.intent, "close_jarvis")

    def test_quit_jarvis(self) -> None:
        result = self.parser.parse("quit jarvis")
        self.assertEqual(result.intent, "close_jarvis")


class TestParserShutdownWindows(TestCase):
    def setUp(self) -> None:
        self.parser = Parser()

    def test_shutdown_computer(self) -> None:
        result = self.parser.parse("shutdown computer")
        self.assertEqual(result.intent, "shutdown_windows")

    def test_shutdown_my_computer(self) -> None:
        result = self.parser.parse("shutdown my computer")
        self.assertEqual(result.intent, "shutdown_windows")

    def test_turn_off_my_pc(self) -> None:
        result = self.parser.parse("turn off my pc")
        self.assertEqual(result.intent, "shutdown_windows")

    def test_power_off_windows(self) -> None:
        result = self.parser.parse("power off windows")
        self.assertEqual(result.intent, "shutdown_windows")

    def test_switch_off_computer(self) -> None:
        result = self.parser.parse("switch off computer")
        self.assertEqual(result.intent, "shutdown_windows")

    def test_shutdown_windows(self) -> None:
        result = self.parser.parse("shutdown windows")
        self.assertEqual(result.intent, "shutdown_windows")


class TestParserShutdownBare(TestCase):
    """Bare 'shutdown' without qualifier → ambiguous."""

    def setUp(self) -> None:
        self.parser = Parser()

    def test_shutdown_is_ambiguous(self) -> None:
        result = self.parser.parse("shutdown")
        self.assertEqual(result.intent, "ambiguous")
        self.assertIn("alternatives", result.entities)

    def test_power_off_is_ambiguous(self) -> None:
        result = self.parser.parse("power off")
        self.assertEqual(result.intent, "ambiguous")
        self.assertIn("alternatives", result.entities)

    def test_turn_off_is_ambiguous(self) -> None:
        result = self.parser.parse("turn off")
        self.assertEqual(result.intent, "ambiguous")
        self.assertIn("alternatives", result.entities)


class TestParserRestart(TestCase):
    def setUp(self) -> None:
        self.parser = Parser()

    def test_restart(self) -> None:
        result = self.parser.parse("restart")
        self.assertEqual(result.intent, "restart")

    def test_reboot(self) -> None:
        result = self.parser.parse("reboot")
        self.assertEqual(result.intent, "restart")

    def test_restart_my_pc(self) -> None:
        result = self.parser.parse("restart my pc")
        self.assertEqual(result.intent, "restart")

    def test_reboot_windows(self) -> None:
        result = self.parser.parse("reboot windows")
        self.assertEqual(result.intent, "restart")

    def test_restart_computer(self) -> None:
        result = self.parser.parse("restart computer")
        self.assertEqual(result.intent, "restart")


class TestParserOpenNotepadCheck(TestCase):
    """Verify the basic scenario 'Open Notepad' works end-to-end."""

    def setUp(self) -> None:
        self.parser = Parser()

    def test_open_notepad(self) -> None:
        result = self.parser.parse("open notepad")
        self.assertEqual(result.intent, "open_app")
        self.assertEqual(result.entities.get("app_name"), "notepad")
        self.assertGreaterEqual(result.confidence, 1.0)

    def test_close_notepad(self) -> None:
        result = self.parser.parse("close notepad")
        self.assertEqual(result.intent, "close_app")
        self.assertEqual(result.entities.get("app_name"), "notepad")
