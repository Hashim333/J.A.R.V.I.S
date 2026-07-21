"""
run.py

Interactive runtime entry point for JARVIS.

This file creates all the core components, wires them together, and
runs the main event loop. It supports both text and voice commands.
"""

from __future__ import annotations

import logging
import os
import queue
import re
import threading
import time
import sys
from brain import Brain
from brain.parser import Parser
from brain.planner import Planner
from executor.executor import Executor
from automation.registry import Registry
from automation.handlers import AppsHandler, BrowserHandler, MouseHandler, KeyboardHandler
from response.manager import ResponseManager
from services import ServiceManager, WakeWordService, ListenerService, ConversationManager, ConversationState
from voice.microphone_stream import MicrophoneStream
from voice.pipeline import VoiceConversationPipeline
from voice.manager import VoiceManager

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("run")


HEADER = """=================================================
JARVIS
================================================"""

DEBUG = os.environ.get("DEBUG", "").casefold() in {"1", "true", "yes", "on"}

_WAKE_PHRASE = "jarvis"
_WAKE_PATTERN = re.compile(rf'\b{re.escape(_WAKE_PHRASE)}\b', re.IGNORECASE)


def _strip_wake_word(text: str) -> str | None:
    """Remove the wake phrase from text, return remaining command or None if only wake word."""
    stripped = _WAKE_PATTERN.sub("", text)
    stripped = re.sub(r"\s+", " ", stripped).strip()
    return stripped if stripped else None


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
    response_manager = ResponseManager(debug=DEBUG)

    # --- 2. Single command mode ---
    if len(sys.argv) > 1:
        executor = Executor(registry)
        brain = Brain(parser, planner, executor)
        command = " ".join(sys.argv[1:])
        print(f"Executing single command: '{command}'")
        response = brain.process(command)
        response_manager.present_console(response)
        return

    # --- 3. Create and Wire Services ---
    command_queue = queue.Queue()
    wake_word_detected = threading.Event()

    microphone_stream = MicrophoneStream(
        chunk_size=1024,
        sample_rate=16000,
    )

    listener_service = ListenerService(
        microphone_stream=microphone_stream,
    )
    wake_word_service = WakeWordService(
        wake_word_detected_event=wake_word_detected,
        microphone_stream=microphone_stream,
    )

    # --- 4. Register Automation Handlers ---
    def _voice_input() -> str | None:
        result = listener_service.listen_for_command()
        return result.text if result.success else None

    apps_handler = AppsHandler()
    mouse_handler = MouseHandler()
    keyboard_handler = KeyboardHandler()
    browser_handler = BrowserHandler()
    registry.register("open_app", apps_handler)
    registry.register("close_app", apps_handler)
    registry.register("open_website", browser_handler)
    registry.register("search", browser_handler)
    registry.register("move_mouse", mouse_handler)
    registry.register("left_click", mouse_handler)
    registry.register("right_click", mouse_handler)
    registry.register("double_click", mouse_handler)
    registry.register("scroll", mouse_handler)
    registry.register("type_text", keyboard_handler)
    registry.register("hotkey", keyboard_handler)

    executor = Executor(registry, voice_input=_voice_input)
    brain = Brain(parser, planner, executor)

    service_manager = ServiceManager()
    service_manager.register("listener", listener_service)
    service_manager.register("wake_word", wake_word_service)

    # --- 5. Create Voice Manager ---
    voice_manager = VoiceManager()

    # --- 6. Create Voice Pipeline ---
    pipeline = VoiceConversationPipeline(
        listener_service=listener_service,
        voice_manager=voice_manager,
        microphone_stream=microphone_stream,
        max_retries=3,
        capture_timeout=10.0,
    )

    # --- 7. Create Conversation Manager ---
    conversation_manager = ConversationManager(
        wake_word_service=wake_word_service,
        listener_service=listener_service,
        activity_timeout=30.0,
    )

    # --- 8. Start Microphone (once, long-lived) ---
    print("Starting microphone stream...")
    microphone_stream.start()

    # --- 9. Start Services ---
    _report_service_results("initialize", service_manager.initialize_all())
    _report_service_results("start", service_manager.start_all())
    print(service_manager.list_services())

    print("Brain Ready")
    print("Parser Ready")
    print("Planner Ready")
    print("Executor Ready")
    print("Service Manager Ready")
    print()
    print("JARVIS is running in dual mode (voice and text).")
    print("Say 'JARVIS' or type a command.")
    print()

    # --- 10. Start Text Input Thread ---
    input_thread = threading.Thread(
        target=_text_input_loop, args=(command_queue,), daemon=True
    )
    input_thread.start()

    # --- 11. Main Orchestration Loop ---
    logger.info("Entering main loop — wake word and text input active")
    try:
        while True:
            # ================================================================
            # Text commands (always processed, non-blocking)
            # ================================================================
            try:
                command = command_queue.get_nowait()

                # --- Built-in commands (exit, help) — always available ---
                if command.casefold() in {"exit", "quit"}:
                    print("Shutting down JARVIS...")
                    print("Goodbye.")
                    break
                if command.casefold() == "help":
                    print(HELP_TEXT)
                    continue

                # --- Sleep command — handled before brain processing ---
                if conversation_manager.is_sleep_command(command):
                    if conversation_manager.state == ConversationState.ACTIVE_CONVERSATION:
                        conversation_manager.transition_to_standby(reason="sleep command")
                        print("\nListening for wake word or text command...")
                    else:
                        print("JARVIS is already in standby mode.")
                    continue

                # --- Regular text command ---
                logger.info("Processing text command: '%s'", command)
                response = brain.process(command)
                response_manager.present_console(response)

                # Handle confirmation flow
                if getattr(response, "needs_clarification", False) and (
                    "Are you sure" in (response.clarification_question or "")
                    or "confirm" in (response.message or "").casefold()
                ):
                    print("(waiting for confirmation...)")
                    try:
                        answer = input("> ")
                    except (KeyboardInterrupt, EOFError):
                        answer = ""
                    if answer.strip().casefold() in ("yes", "y", "confirm", "do it", "go ahead"):
                        logger.info("User confirmed, re-processing command")
                        response = brain.process(command, confirmed=True)
                        response_manager.present_console(response)
                    else:
                        print("Action cancelled.")
                    continue

                # Enter conversation mode so subsequent commands don't need wake word
                if conversation_manager.state == ConversationState.STANDBY:
                    conversation_manager.transition_to_active()
                else:
                    conversation_manager.reset_activity()
                continue
            except queue.Empty:
                pass

            # ================================================================
            # Voice commands (state-dependent)
            # ================================================================
            if conversation_manager.state == ConversationState.STANDBY:
                # -- STANDBY: accept wake word only --
                if wake_word_detected.is_set():
                    command = pipeline.wait_for_command(wake_word_detected)

                    if command:
                        print(f"Command: '{command}'")
                        logger.info("Processing voice command: '%s'", command)
                        response = brain.process(command)
                        response_manager.present_console(response)

                        # Handle confirmation for voice commands
                        if getattr(response, "needs_clarification", False) and (
                            "Are you sure" in (response.clarification_question or "")
                        ):
                            print("Say 'yes' to confirm, or say 'cancel' to abort.")
                            confirm_result = listener_service.listen_for_command(timeout=5.0)
                            if confirm_result.success and confirm_result.text:
                                answer = confirm_result.text.strip().casefold()
                                if answer in ("yes", "y", "confirm", "do it", "go ahead"):
                                    logger.info("Voice confirmation received")
                                    response = brain.process(command, confirmed=True)
                                    response_manager.present_console(response)

                        print("\nConversation mode active — keep giving commands.")
                        conversation_manager.transition_to_active()
                    else:
                        print("Could not understand command.")
                        logger.warning("Voice command failed after all retries")
                        wake_word_service.reset_for_wake()
                        print("\nListening for wake word or text command...")

            elif conversation_manager.state == ConversationState.ACTIVE_CONVERSATION:
                # -- ACTIVE_CONVERSATION: no wake word, listen for commands --
                if conversation_manager.is_expired:
                    conversation_manager.transition_to_standby(reason="timeout")
                    print("\nConversation timed out. Listening for wake word or text command...")
                    continue

                listen_to = min(5.0, max(1.0, conversation_manager.remaining_time))
                logger.info("Listening for command (state=ACTIVE_CONVERSATION, timeout=%.1f)", listen_to)
                result = listener_service.listen_for_command(timeout=listen_to)

                if result.success and result.text:
                    if conversation_manager.is_sleep_command(result.text):
                        print("Sleep command received. Returning to standby.")
                        conversation_manager.transition_to_standby(reason="sleep command")
                        print("\nListening for wake word or text command...")
                        continue

                    print(f"Command: '{result.text}'")
                    logger.info("Processing conversation command: '%s'", result.text)
                    response = brain.process(result.text)
                    response_manager.present_console(response)

                    if getattr(response, "needs_clarification", False) and (
                        "Are you sure" in (response.clarification_question or "")
                    ):
                        print("Say 'yes' to confirm, or anything else to cancel.")
                        confirm_result = listener_service.listen_for_command(timeout=5.0)
                        if confirm_result.success and confirm_result.text:
                            answer = confirm_result.text.strip().casefold()
                            if answer in ("yes", "y", "confirm", "do it", "go ahead"):
                                logger.info("Voice confirmation received")
                                response = brain.process(result.text, confirmed=True)
                                response_manager.present_console(response)

                    conversation_manager.reset_activity()
                    print("\nConversation mode active — keep giving commands.")
                else:
                    if conversation_manager.is_expired:
                        conversation_manager.transition_to_standby(reason="timeout")
                        print("\nConversation timed out. Listening for wake word or text command...")

            time.sleep(0.05)

    except KeyboardInterrupt:
        print("\nShutting down JARVIS...")
        print("Goodbye.")
    finally:
        # Close stdin so the daemon _text_input_loop thread gets EOFError
        # and exits cleanly instead of holding the stdin buffer lock at
        # interpreter shutdown (which would cause a fatal error).
        try:
            sys.__stdin__.close()
        except Exception:
            pass
        logger.info("Shutting down all services")
        _report_service_results("shutdown", service_manager.shutdown_all())
        logger.info("Shutting down microphone stream")
        microphone_stream.shutdown()



if __name__ == "__main__":
    main()
