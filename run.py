"""
run.py

Interactive runtime entry point for JARVIS.

This file creates one Brain instance and sends user text through
Brain.process(). It does not bypass Brain or call lower pipeline layers.
"""

from __future__ import annotations

import os

from brain import Brain
from response.manager import ResponseManager
from services import ServiceManager, WakeWordService


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


def _display_history(history: list[str]) -> None:
    if not history:
        print("No commands in history for this session.")
        return
    for i, command in enumerate(history, 1):
        print(f"  {i}: {command}")


def _report_service_results(action: str, results: dict[str, str]) -> None:
    """
    Print any non-"ok" results from a ServiceManager bulk operation.

    With no services registered yet, results is always empty and this
    prints nothing. Kept in place so it does the right thing the
    moment the first real service is registered.
    """
    failures = {name: outcome for name, outcome in results.items() if outcome != "ok"}
    if not failures:
        return
    print(f"Warning: issues while running {action} on services:")
    for name, outcome in failures.items():
        print(f"  {name}: {outcome}")


def main() -> None:
    print(HEADER)
    print()
    print("Initializing...")
    print()

    brain = Brain()
    response_manager = ResponseManager(debug=DEBUG)

    service_manager = ServiceManager()
    service_manager.register("wake_word", WakeWordService())
    _report_service_results("initialize", service_manager.initialize_all())
    _report_service_results("start", service_manager.start_all())

    print("Brain Ready")
    print("Parser Ready")
    print("Planner Ready")
    print("Executor Ready")
    print("Service Manager Ready")
    print()
    print("JARVIS Ready.")
    print()

    history: list[str] = []

    try:
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
            response_manager.present_console(response)
    finally:
        _report_service_results("shutdown", service_manager.shutdown_all())


if __name__ == "__main__":
    main()
