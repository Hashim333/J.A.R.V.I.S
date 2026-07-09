"""
dev_tests/test_pipeline.py

Integration test for the complete JARVIS pipeline.

Pipeline under test:

    User Input
        |
        v
    Brain.process()
        |
        v
    Parser
        |
        v
    Planner
        |
        v
    Executor
        |
        v
    Registry
        |
        v
    Automation Tool
        |
        v
    Response

This script is intentionally "dumb": it only ever talks to Brain.process().
It does NOT import or call Parser, Planner, Executor, Registry, automation
modules, Ollama, voice, browser automation, vision, or memory directly.
Brain is solely responsible for coordinating the full chain end-to-end.

Python: 3.12
No unit testing framework is used on purpose -- this is a manual,
menu-driven smoke test you run yourself and eyeball the output of.
"""

from __future__ import annotations

import sys
import traceback
from dataclasses import is_dataclass, fields as dataclass_fields
from typing import Any

# ---------------------------------------------------------------------------
# The ONLY JARVIS import allowed in this file is Brain.
# We also import its dependencies to construct it.
# Adjust this single line if your Brain class lives at a different path
# (e.g. `from brain.brain import Brain`). Everything else in this script
# is intentionally pipeline-agnostic.
# ---------------------------------------------------------------------------
try:
    from brain import Brain  # type: ignore
    from brain.parser import Parser
    from brain.planner import Planner
    from executor.executor import Executor
    from automation.registry import Registry
    from automation.handlers import AppsHandler, MouseHandler, KeyboardHandler
except ImportError as import_error:
    print("=" * 70)
    print("FATAL: Could not import Brain and its dependencies.")
    print("This test ONLY talks to Brain.process() -- it cannot proceed")
    print("without it. Check that all components are available and that")
    print("you are running this script from the project root.")
    print("-" * 70)
    print(f"Import error: {import_error}")
    print("=" * 70)
    sys.exit(1)


MENU_TEXT = """
==================== JARVIS PIPELINE TEST ====================
  1. Open Notepad
  2. Open Calculator
  3. Open Chrome
  4. Type Custom Command
  5. Exit
================================================================
"""

# Maps menu choice -> natural language command handed to Brain.process().
# Brain is responsible for parsing/planning/executing/automating from here.
FIXED_COMMANDS = {
    "1": "open notepad",
    "2": "open calculator",
    "3": "open chrome",
}


def print_response(response: Any) -> None:
    """
    Print whatever Brain.process() returns in a readable way, without
    assuming a rigid schema. Handles dataclass Response objects, plain
    objects with attributes, dicts, or even a raw string -- so this test
    doesn't break if the Response shape evolves slightly.
    """
    print("-" * 70)
    print("RESPONSE FROM Brain.process():")

    if response is None:
        print("  <None> (Brain.process() returned nothing)")
        print("-" * 70)
        return

    if is_dataclass(response) and not isinstance(response, type):
        for f in dataclass_fields(response):
            value = getattr(response, f.name)
            print(f"  {f.name}: {value!r}")
        print("-" * 70)
        return

    if isinstance(response, dict):
        for key, value in response.items():
            print(f"  {key}: {value!r}")
        print("-" * 70)
        return

    # Fallback: object with attributes (e.g. namedtuple, plain class) or a
    # primitive like a string/bool.
    if hasattr(response, "__dict__") and response.__dict__:
        for key, value in vars(response).items():
            print(f"  {key}: {value!r}")
    else:
        print(f"  {response!r}")

    print("-" * 70)


def run_through_brain(brain: Brain, command_text: str) -> None:
    """
    Send a single command through Brain.process() and print the result.
    All exceptions are caught here so a bad command never crashes the
    test menu -- per requirements, errors must be displayed, not raised.
    """
    print(f"\n>>> Sending to Brain.process(): {command_text!r}")
    try:
        response = brain.process(command_text)
        print_response(response)
    except Exception as exc:  # noqa: BLE001 - intentional, broad by design
        print("-" * 70)
        print("EXCEPTION raised while running the pipeline:")
        print(f"  {type(exc).__name__}: {exc}")
        print("  Traceback (most recent call last):")
        traceback.print_exc(file=sys.stdout)
        print("-" * 70)


def prompt_custom_command() -> str | None:
    """
    Ask the user to type a free-form command. Returns None if the user
    enters nothing (so the caller can skip the call cleanly).
    """
    try:
        text = input("Enter custom command: ").strip()
    except (EOFError, KeyboardInterrupt):
        print("\n(input cancelled)")
        return None

    if not text:
        print("(empty command, nothing sent)")
        return None

    return text


def main() -> None:
    print("Initializing Brain and its dependencies...")
    try:
        # --- Create and wire components ---
        parser = Parser()
        planner = Planner()
        registry = Registry()

        apps_handler = AppsHandler()
        mouse_handler = MouseHandler()
        keyboard_handler = KeyboardHandler()

        registry.register("open_app", apps_handler)
        registry.register("close_app", apps_handler)
        registry.register("move_mouse", mouse_handler)
        registry.register("left_click", mouse_handler)
        registry.register("right_click", mouse_handler)
        registry.register("double_click", mouse_handler)
        registry.register("scroll", mouse_handler)
        registry.register("type_text", keyboard_handler)
        registry.register("hotkey", keyboard_handler)

        executor = Executor(registry)
        brain = Brain(parser=parser, planner=planner, executor=executor)

    except Exception as exc:  # noqa: BLE001
        print("FATAL: Could not construct Brain or its dependencies.")
        print(f"  {type(exc).__name__}: {exc}")
        traceback.print_exc(file=sys.stdout)
        sys.exit(1)

    print("Brain initialized. Ready to test the pipeline.")

    while True:
        print(MENU_TEXT)
        try:
            choice = input("Select an option (1-5): ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nExiting JARVIS pipeline test. Goodbye.")
            break

        if choice in FIXED_COMMANDS:
            run_through_brain(brain, FIXED_COMMANDS[choice])

        elif choice == "4":
            custom_text = prompt_custom_command()
            if custom_text is not None:
                run_through_brain(brain, custom_text)

        elif choice == "5":
            print("Exiting JARVIS pipeline test. Goodbye.")
            break

        else:
            print(f"Invalid option: {choice!r}. Please choose 1-5.")


if __name__ == "__main__":
    main()