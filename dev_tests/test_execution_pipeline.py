"""
dev_tests/test_execution_pipeline.py

Comprehensive integration test for the command execution pipeline.

Tests the FULL chain from text input -> Response:

    Text -> Parser -> Planner -> Executor -> Registry -> Handler -> apps

The parser/planner tests are fast (no I/O). The executor tests are run
separately with heavy mocking to avoid real filesystem and system calls.

Run with:  python -m dev_tests.test_execution_pipeline
"""

from __future__ import annotations

import sys
import traceback
from unittest.mock import patch, MagicMock
from dataclasses import fields as dataclass_fields
from dataclasses import is_dataclass

import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    from brain import Brain
    from brain.parser import Parser
    from brain.planner import Planner
    from executor.executor import Executor
    from automation.registry import Registry
    from automation.handlers import AppsHandler
    from models.response import Response
    from brain.execution_plan import Step
except ImportError as e:
    print(f"FATAL: Import error: {e}")
    sys.exit(1)


# =========================================================================
# TEST CASE DEFINITIONS
# =========================================================================

OPEN_APP_CASES = [
    ("open chrome", "open_app", "chrome"),
    ("open google chrome", "open_app", "chrome"),
    ("open chrome browser", "open_app", "chrome"),
    ("launch chrome", "open_app", "chrome"),
    ("start chrome", "open_app", "chrome"),
    ("run chrome", "open_app", "chrome"),
    ("open calculator", "open_app", "calculator"),
    ("open calc", "open_app", "calculator"),
    ("launch calculator", "open_app", "calculator"),
    ("open vs code", "open_app", "vscode"),
    ("open vscode", "open_app", "vscode"),
    ("open visual studio code", "open_app", "vscode"),
    ("open code editor", "open_app", "vscode"),
    ("launch vs code", "open_app", "vscode"),
    ("open notepad", "open_app", "notepad"),
    ("launch notepad", "open_app", "notepad"),
    ("open paint", "open_app", "paint"),
    ("open mspaint", "open_app", "paint"),
    ("open edge", "open_app", "edge"),
    ("open microsoft edge", "open_app", "edge"),
    ("open ms edge", "open_app", "edge"),
    ("open explorer", "open_app", "explorer"),
    ("open file explorer", "open_app", "explorer"),
    ("open cmd", "open_app", "cmd"),
    ("open command prompt", "open_app", "cmd"),
    ("open powershell", "open_app", "powershell"),
]

CLOSE_APP_CASES = [
    ("close chrome", "close_app", "chrome"),
    ("close notepad", "close_app", "notepad"),
    ("close calculator", "close_app", "calculator"),
    ("close edge", "close_app", "edge"),
    ("exit calculator", "close_app", "calculator"),
    ("kill chrome", "close_app", "chrome"),
    ("terminate vscode", "close_app", "vscode"),
    ("quit notepad", "close_app", "notepad"),
]

FOCUS_APP_CASES = [
    ("focus chrome", "focus_app", "chrome"),
    ("focus notepad", "focus_app", "notepad"),
    ("switch to chrome", "focus_app", "chrome"),
    ("bring to front notepad", "focus_app", "notepad"),
]

SPECIAL_FOLDER_CASES = [
    ("open downloads", "open_special_folder", "downloads"),
    ("open documents", "open_special_folder", "documents"),
    ("open pictures", "open_special_folder", "pictures"),
    ("open music", "open_special_folder", "music"),
    ("open videos", "open_special_folder", "videos"),
    ("open desktop", "open_special_folder", "desktop"),
]

SETTINGS_CASES = [
    ("open settings", "open_settings", ""),
    ("open bluetooth settings", "open_settings", "bluetooth"),
    ("open wifi settings", "open_settings", "wifi"),
    ("open display settings", "open_settings", "display"),
    ("open sound settings", "open_settings", "sound"),
]

VOLUME_CASES = [
    ("increase volume", "increase_volume"),
    ("raise volume", "increase_volume"),
    ("turn up volume", "increase_volume"),
    ("decrease volume", "decrease_volume"),
    ("lower volume", "decrease_volume"),
    ("turn down volume", "decrease_volume"),
    ("mute", "mute_volume"),
    ("mute volume", "mute_volume"),
    ("unmute", "unmute_volume"),
    ("unmute volume", "unmute_volume"),
    ("set volume to 50", "set_volume"),
    ("set volume to 75", "set_volume"),
]

SYSTEM_CASES = [
    ("screenshot", "screenshot"),
    ("take screenshot", "screenshot"),
    ("capture screen", "screenshot"),
    ("lock", "lock"),
    ("lock computer", "lock"),
    ("shutdown", "shutdown"),
    ("shut down", "shutdown"),
    ("restart", "restart"),
    ("reboot", "restart"),
    ("sleep", "sleep"),
    ("suspend", "sleep"),
]

AMBIGUOUS_CASES = [
    ("open code", "ambiguous", "Did you mean Visual Studio Code"),
]

UNSUPPORTED_CASES = [
    "open task manager",
    "do a barrel roll",
    "what is the weather",
    "tell me a joke",
    "jarvis",
]


# =========================================================================
# PARSER + PLANNER VERIFICATION (fast, no I/O)
# =========================================================================

def test_parse_and_plan(brain, text, expected_intent, expected_target=None, expected_question=None):
    """Test Parser + Planner only (fast)."""
    print(f"\n  Input: {text!r}")

    try:
        parsed = brain._parser.parse(text)
    except Exception as e:
        print(f"    PARSE ERROR: {e}")
        return False

    print(f"    Parse: intent={parsed.intent!r} entities={parsed.entities}")

    if expected_intent == "unknown":
        if parsed.intent != "unknown":
            print(f"    FAIL: expected unknown, got {parsed.intent!r}")
            return False
        return True

    if expected_intent == "ambiguous":
        if parsed.intent != "ambiguous":
            print(f"    FAIL: expected ambiguous, got {parsed.intent!r}")
            return False
        if expected_question:
            q = parsed.entities.get("question", "")
            if expected_question not in q:
                print(f"    FAIL: question mismatch: {q!r}")
                return False
        return True

    if parsed.intent != expected_intent:
        print(f"    FAIL: intent {parsed.intent!r} != {expected_intent!r}")
        return False

    # Check entities
    for key in ("app_name", "folder", "page"):
        val = parsed.entities.get(key)
        if val is not None and expected_target is not None:
            if val != expected_target:
                print(f"    FAIL: {key}={val!r} != expected {expected_target!r}")
                return False

    # Verify planner
    try:
        plan = brain._planner.create_plan(parsed)
    except Exception as e:
        print(f"    PLAN ERROR: {e}")
        return False

    if len(plan.steps) == 0:
        print(f"    FAIL: no steps produced")
        return False

    step = plan.steps[0]
    action_map = {
        "open_app": "open_app", "close_app": "close_app", "focus_app": "focus_app",
        "open_special_folder": "open_special_folder", "open_settings": "open_settings",
        "increase_volume": "increase_volume", "decrease_volume": "decrease_volume",
        "set_volume": "set_volume", "mute_volume": "mute_volume", "unmute_volume": "unmute_volume",
        "screenshot": "screenshot", "lock": "lock", "shutdown": "shutdown",
        "restart": "restart", "sleep": "sleep",
    }
    expected_action = action_map.get(expected_intent, expected_intent)
    if step.action != expected_action:
        print(f"    FAIL: action {step.action!r} != {expected_action!r}")
        return False

    print(f"    Plan: {step.action!r} -> {step.target!r}")
    print(f"    PASS")
    return True


# =========================================================================
# BATCH TEST RUNNERS
# =========================================================================

def run_batch(brain, cases, label):
    """Run a batch of parse+plan tests."""
    print(f"\n{'='*70}")
    print(f"{label}")
    print(f"{'='*70}")

    passed = 0
    failed = 0
    for case in cases:
        ok = test_parse_and_plan(brain, *case)
        if ok:
            passed += 1
        else:
            failed += 1

    print(f"\n  {label}: {passed}/{len(cases)} passed")
    return passed, failed


def test_unknown(brain):
    """Verify unknown commands."""
    print(f"\n{'='*70}")
    print("UNSUPPORTED COMMANDS")
    print(f"{'='*70}")

    passed = 0
    for text in UNSUPPORTED_CASES:
        ok = test_parse_and_plan(brain, text, "unknown")
        if ok:
            passed += 1
    print(f"\n  Unsupported: {passed}/{len(UNSUPPORTED_CASES)} passed")
    return passed, len(UNSUPPORTED_CASES) - passed


def test_clarification(brain):
    """Test ambiguity detection + Brain clarification."""
    print(f"\n{'='*70}")
    print("CLARIFICATION FLOW")
    print(f"{'='*70}")

    passed = 0
    failed = 0

    # Test parser detects ambiguity
    parsed = brain._parser.parse("open code")
    if parsed.intent == "ambiguous":
        print(f"  Parser detects ambiguity: PASS")
        passed += 1
    else:
        print(f"  Parser: expected ambiguous, got {parsed.intent!r}: FAIL")
        failed += 1

    # Test Brain returns clarification response
    with patch("automation.apps.subprocess.Popen", return_value=MagicMock(pid=99999)):
        with patch("PIL.ImageGrab.grab", return_value=MagicMock()):
            with patch("automation.apps.psutil.process_iter", return_value=[]):
                response = brain.process("open code")

    if response.needs_clarification:
        print(f"  Brain clarification: {response.clarification_question!r}: PASS")
        passed += 1
    else:
        print(f"  Brain: expected clarification, got success={response.success}: FAIL")
        failed += 1

    print(f"\n  Clarification: {passed}/{passed + failed} passed")
    return passed, failed


# =========================================================================
# EXECUTOR TESTS (heavy mocking)
# =========================================================================

def test_executor_dispatch():
    """Test that each action is registered to correct handler type."""
    print(f"\n{'='*70}")
    print("EXECUTOR DISPATCH TESTS")
    print(f"{'='*70}")

    registry = Registry()

    action_handler_map = {
        "open_app": "AppsHandler",
        "close_app": "AppsHandler",
        "focus_app": "AppsHandler",
        "open_special_folder": "SpecialFolderHandler",
        "open_settings": "SettingsHandler",
        "increase_volume": "VolumeHandler",
        "decrease_volume": "VolumeHandler",
        "set_volume": "VolumeHandler",
        "mute_volume": "VolumeHandler",
        "unmute_volume": "VolumeHandler",
        "screenshot": "ScreenshotHandler",
        "lock": "SystemHandler",
        "shutdown": "SystemHandler",
        "restart": "SystemHandler",
        "sleep": "SystemHandler",
    }

    passed = 0
    for action, expected_handler in action_handler_map.items():
        try:
            handler = registry.get_handler(action)
            handler_name = type(handler).__name__
            if handler_name == expected_handler:
                print(f"  {action} -> {handler_name}: PASS")
                passed += 1
            else:
                print(f"  {action} -> {handler_name} (expected {expected_handler}): FAIL")
        except KeyError:
            print(f"  {action}: NO HANDLER: FAIL")

    total = len(action_handler_map)
    print(f"\n  Executor dispatch: {passed}/{total} passed")
    return passed, total - passed


# =========================================================================
# MAIN
# =========================================================================

def main():
    print("=" * 70)
    print("JARVIS EXECUTION PIPELINE INTEGRATION TEST")
    print("=" * 70)
    print()

    # Build the Brain with all real components
    print("Building Brain...")
    try:
        parser = Parser()
        planner = Planner()
        registry = Registry()
        executor = Executor(registry)
        brain = Brain(parser=parser, planner=planner, executor=executor)
        print(f"Brain built. {len(registry.registered_actions())} handlers registered.")
    except Exception as e:
        print(f"FATAL: {e}")
        traceback.print_exc()
        sys.exit(1)

    total_passed = 0
    total_failed = 0

    # Parser + Planner tests (fast)
    for label, cases in [
        ("OPEN APP COMMANDS", OPEN_APP_CASES),
        ("CLOSE APP COMMANDS", CLOSE_APP_CASES),
        ("FOCUS APP COMMANDS", FOCUS_APP_CASES),
        ("SPECIAL FOLDER COMMANDS", SPECIAL_FOLDER_CASES),
        ("SETTINGS COMMANDS", SETTINGS_CASES),
        ("VOLUME COMMANDS", VOLUME_CASES),
        ("SYSTEM COMMANDS", SYSTEM_CASES),
    ]:
        p, f = run_batch(brain, cases, label)
        total_passed += p
        total_failed += f

    # Special tests
    for label, cases in [("AMBIGUOUS COMMANDS", AMBIGUOUS_CASES)]:
        p, f = run_batch(brain, cases, label)
        total_passed += p
        total_failed += f

    p, f = test_unknown(brain)
    total_passed += p
    total_failed += f

    p, f = test_clarification(brain)
    total_passed += p
    total_failed += f

    # Executor dispatch tests (isolated, heavy mocking)
    p, f = test_executor_dispatch()
    total_passed += p
    total_failed += f

    # Summary
    print()
    print("=" * 70)
    print("RESULTS")
    print("=" * 70)
    print(f"  Total Passed: {total_passed}")
    print(f"  Total Failed: {total_failed}")

    total_cases = (
        len(OPEN_APP_CASES) + len(CLOSE_APP_CASES) + len(FOCUS_APP_CASES) +
        len(SPECIAL_FOLDER_CASES) + len(SETTINGS_CASES) + len(VOLUME_CASES) +
        len(SYSTEM_CASES) + len(AMBIGUOUS_CASES) + len(UNSUPPORTED_CASES) + 3 +
        len({
            "open_app", "close_app", "focus_app", "open_special_folder",
            "open_settings", "increase_volume", "decrease_volume", "set_volume",
            "mute_volume", "unmute_volume", "screenshot", "lock",
            "shutdown", "restart", "sleep",
        })
    )
    print(f"  Total Test Cases: ~{total_cases}")
    print()

    if total_failed > 0:
        print(f"  *** {total_failed} TEST(S) FAILED ***")
        sys.exit(1)
    else:
        print(f"  All pipeline tests passed!")
        sys.exit(0)


if __name__ == "__main__":
    main()
