"""
run.py

Interactive runtime entry point for JARVIS.

This file creates one Brain instance and sends user text through
Brain.process(). It does not bypass Brain or call lower pipeline layers.
"""

from __future__ import annotations

from dataclasses import asdict, is_dataclass
from dataclasses import is_dataclass
from typing import Any

from brain import Brain


HEADER = """=================================================
JARVIS
================================================="""


HELP_TEXT = """
Available Commands:

  help                      Show this help message.
  history                   Show your command history for this session.
  exit / quit               Exit JARVIS.

App Management:
  open <app_name>           e.g., open notepad
  close <app_name>          e.g., close calculator

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
    """Prints a friendly, human-readable response."""
    if response is None:
        print("<no response>")
        print("✗ An unexpected error occurred: no response from Brain.")
        return

    if is_dataclass(response) and not isinstance(response, type):
        for key, value in asdict(response).items():
            print(f"{key}: {value}")
    # Handle special case for unknown commands
    if (
        hasattr(response, "message")
        and response.message == "Execution plan had no steps."
    ):
        print("I didn't understand that command.")
        print('Type "help" for available commands.')
        return

    print(response)
    if not is_dataclass(response) or not hasattr(response, "success"):
        print(f"~ Unstructured response: {response}")
        return

    if response.success:
        # Use a generic success message if the response message is empty
        message = response.message or "Action completed successfully."
        print(f"✓ {message}")
    else:
        # Use a generic error message if the response message is empty
        message = response.message or "An unknown error occurred."
        print(f"✗ {message}")
        if response.error:
            print(f"  Details: {response.error}")


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
