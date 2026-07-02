"""
run.py

Interactive runtime entry point for JARVIS.

This file creates one Brain instance and sends user text through
Brain.process(). It does not bypass Brain or call lower pipeline layers.
"""

from __future__ import annotations

import os
from dataclasses import is_dataclass
from typing import Any

from brain import Brain


HEADER = """=================================================
JARVIS
================================================="""

DEBUG = os.environ.get("DEBUG", "").casefold() in {"1", "true", "yes", "on"}


HELP_TEXT = """
Available Commands:

  help                      Show this help message.
  history                   Show your command history for this session.
  exit / quit               Exit JARVIS.

App Management:
  open <app_name>           e.g., open notepad
  close <app_name>          e.g., close calculator

Window Context:
  focus <app_name>          e.g., focus chrome
  active window             Show the active window.
  list windows              Show open windows.

Browser Navigation:
  open <website>            e.g., open youtube
  search <query> on <site>  e.g., search python tutorials on google

Browser Tab Management:
  new tab
  close tab
  close all tabs
  next tab
  previous tab
  reopen tab
  refresh page
  hard refresh
"""


def _display_response(response: Any) -> None:
    """Print a friendly, human-readable response."""
    if response is None:
        print("An unexpected error occurred: no response from Brain.")
        return

    if (
        hasattr(response, "message")
        and response.message
        in {"Execution plan had no steps.", "Execution plan had no steps to run."}
    ):
        print("I didn't understand that command.")
        print('Type "help" for available commands.')
        return

    if not is_dataclass(response) or not hasattr(response, "success"):
        print(f"Unstructured response: {response}")
        return

    if response.success:
        print(_friendly_success_message(response))
        return

    message = response.message or "An unknown error occurred."
    print(message)
    if DEBUG and response.error:
        print(f"Details: {response.error}")


def _friendly_success_message(response: Any) -> str:
    data = getattr(response, "data", {}) or {}
    intent = data.get("intent")
    results = data.get("results") or []
    first_result = results[0].get("result") if results else None

    if intent == "active_window":
        return f"Active window: {first_result or 'None'}"

    if intent == "list_windows":
        if not first_result:
            return "No open windows found."
        return "Open windows:\n" + "\n".join(f"  {title}" for title in first_result)

    if isinstance(first_result, bool) and first_result is False:
        return "I could not complete that action."

    return "Done."


def _display_history(history: list[str]) -> None:
    if not history:
        print("No commands in history for this session.")
        return
    for i, command in enumerate(history, 1):
        print(f"  {i}: {command}")


def main() -> None:
    print(HEADER)
    print()
    print("Initializing...")
    print()

    brain = Brain()

    print("Brain Ready")
    print("Parser Ready")
    print("Planner Ready")
    print("Executor Ready")
    print()
    print("JARVIS Ready.")
    print()

    history: list[str] = []

    while True:
        try:
            command = input("> ")
        except KeyboardInterrupt:
            print()
            print("Shutting down JARVIS...")
            print()
            print("Goodbye.")
            break
        except EOFError:
            print()
            print("Shutting down JARVIS...")
            print()
            print("Goodbye.")
            break

        command = command.strip()
        if not command:
            continue

        if command.casefold() in {"exit", "quit"}:
            print("Shutting down JARVIS...")
            print()
            print("Goodbye.")
            break

        if command.casefold() == "help":
            print(HELP_TEXT)
            continue

        if command.casefold() == "history":
            _display_history(history)
            continue

        history.append(command)

        response = brain.process(command)
        _display_response(response)


if __name__ == "__main__":
    main()
