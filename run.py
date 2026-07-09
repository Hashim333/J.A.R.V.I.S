"""
run.py

Interactive runtime entry point for JARVIS.

This file creates all the core components, wires them together, and
runs the main event loop. It supports both text and voice commands.
"""

from __future__ import annotations

import os
import queue
import threading
import time
import sys
from brain import Brain
from brain.parser import Parser
from brain.planner import Planner
from executor.executor import Executor
from automation.registry import Registry
from automation.handlers import AppsHandler, MouseHandler, KeyboardHandler
from response.manager import ResponseManager
from services import ServiceManager, WakeWordService, ListenerService


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
    """
    failures = {name: outcome for name, outcome in results.items() if outcome != "ok"}
    if not failures:
        return
    print(f"Warning: issues while running {action} on services:")
    for name, outcome in failures.items():
        print(f"  {name}: {outcome}")


def _text_input_loop(command_queue: queue.Queue[str]) -> None:
    """
    A loop that runs in a separate thread to handle text-based input
    without blocking the main voice loop.
    """
    history: list[str] = []
    while True:
        try:
            command = input("> ")
        except (KeyboardInterrupt, EOFError):
            # Signal the main thread to exit
            command_queue.put("exit")
            break

        command = command.strip()
        if not command:
            continue

        if command.casefold() == "history":
            _display_history(history)
            continue

        history.append(command)
        command_queue.put(command)


def main() -> None:
    print(HEADER)
    print()
    print("Initializing...")
    print()

    # --- 1. Create Core Components ---
    parser = Parser()
    planner = Planner()
    registry = Registry()
    executor = Executor(registry)
    brain = Brain(parser, planner, executor)
    response_manager = ResponseManager(debug=DEBUG)

    # --- 2. Register Automation Handlers ---
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

    # --- 3. Single command mode ---
    if len(sys.argv) > 1:
        command = " ".join(sys.argv[1:])
        print(f"Executing single command: '{command}'")
        response = brain.process(command)
        response_manager.present_console(response)
        return

    # --- 4. Create and Wire Services ---
    command_queue = queue.Queue()
    wake_word_detected = threading.Event()
    listener_service = ListenerService()
    wake_word_service = WakeWordService(wake_word_detected_event=wake_word_detected)

    service_manager = ServiceManager()
    service_manager.register("listener", listener_service)
    service_manager.register("wake_word", wake_word_service)

    # --- 5. Start Services ---
    _report_service_results("initialize", service_manager.initialize_all())
    _report_service_results("start", service_manager.start_all())

    print("Brain Ready")
    print("Parser Ready")
    print("Planner Ready")
    print("Executor Ready")
    print("Service Manager Ready")
    print()
    print("JARVIS is running in dual mode (voice and text).")
    print("Say 'JARVIS' or type a command.")
    print()

    # --- 6. Start Text Input Thread ---
    input_thread = threading.Thread(
        target=_text_input_loop, args=(command_queue,), daemon=True
    )
    input_thread.start()

    # --- 7. Main Orchestration Loop ---
    try:
        while True:
            # Check for a voice command
            if wake_word_detected.is_set():
                print("Wake word detected. Listening for command...")
                wake_word_detected.clear()
                result = listener_service.listen_for_command()

                if result.success and result.text:
                    print(f"Heard: '{result.text}'")
                    # response = brain.process(result.text)
                    # response_manager.present_console(response)
                    response = brain.process(...)

                    print("\n========== DEBUG ==========")
                    print("Success :", response.success)
                    print("Message :", response.message)
                    print("Error   :", response.error)
                    print("Data    :", response.data)
                    print("===========================\n")

                    response_manager.present_console(response)
                else:
                    print(f"Could not understand command. Error: {result.error}")
                print("\nListening for wake word or text command...")

            # Check for a text command
            try:
                command = command_queue.get_nowait()
                if command.casefold() in {"exit", "quit"}:
                    print("Shutting down JARVIS...")
                    print("Goodbye.")
                    break
                if command.casefold() == "help":
                    print(HELP_TEXT)
                    continue

                response = brain.process(command)
                response_manager.present_console(response)
            except queue.Empty:
                pass  # No text command, continue loop

            time.sleep(0.1)

    except KeyboardInterrupt:
        print("\nShutting down JARVIS...")
        print("Goodbye.")
    finally:
        _report_service_results("shutdown", service_manager.shutdown_all())



if __name__ == "__main__":
    main()
