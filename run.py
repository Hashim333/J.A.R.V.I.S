"""
run.py

JARVIS — desktop UI entry point.

Launches the full-screen QML interface as the primary interaction mode.
The terminal displays debug logs only.

Usage:
    python run.py                    # normal desktop UI mode
    python run.py <command>          # execute a single command and exit
"""

from __future__ import annotations

import logging
from config.settings import settings
import queue
import re
import sys
import threading
import time
from brain import Brain
from brain.parser import Parser
from brain.planner import Planner
from context_manager.context_manager import ContextManager
from executor.executor import Executor
from verification.task_verifier import TaskVerifier
from automation.registry import Registry
from automation.handlers import AppsHandler, BrowserHandler, MouseHandler, KeyboardHandler
from response.manager import ResponseManager
from services import ServiceManager, WakeWordService, ListenerService, ConversationManager, ConversationState
from voice.microphone_stream import MicrophoneStream
from voice.pipeline import VoiceConversationPipeline
from voice.manager import VoiceManager
from voice.engine import VoiceEngine
from ui.app import JarvisApp

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("run")

DEBUG = settings.debug

_WAKE_PHRASE = "jarvis"
_WAKE_PATTERN = re.compile(rf'\b{re.escape(_WAKE_PHRASE)}\b', re.IGNORECASE)


def _strip_wake_word(text: str) -> str | None:
    stripped = _WAKE_PATTERN.sub("", text)
    stripped = re.sub(r"\s+", " ", stripped).strip()
    if not stripped:
        return None
    return stripped


def _report_service_results(action: str, results: dict[str, str]) -> None:
    failures = {name: outcome for name, outcome in results.items() if outcome != "ok"}
    if not failures:
        return
    logger.warning("Issues while running %s on services:", action)
    for name, outcome in failures.items():
        logger.warning("  %s: %s", name, outcome)


def _on_backend_error(bridge, microphone_stream, service_manager, exc):
    """Log a backend error and communicate it to the UI."""
    logger.error("Backend error: %s", exc, exc_info=True)
    try:
        bridge.set_core_state("error")
        bridge.show_subtitle("An error occurred — check the logs.")
    except Exception:
        pass


def _present_response(
    bridge, response_manager, response, voice_engine, microphone_stream=None
) -> None:
    """Show a response on the UI and speak it via voice engine.
    
    Mic muting during TTS playback is handled automatically by
    VoicePlayer lifecycle callbacks (wired in main()), so the mic
    stays muted for the entire playback duration plus a 200ms cooldown."""
    subtitle = response_manager.console_text(response)
    bridge.show_subtitle(subtitle)
    if response_manager._voice_enabled:
        message = response_manager.voice_text(response)
        if message:
            try:
                voice_engine.speak(message)
            except Exception:
                pass


def _backend_loop(
    bridge,
    command_queue,
    wake_word_detected,
    brain,
    context_manager,
    response_manager,
    listener_service,
    wake_word_service,
    conversation_manager,
    voice_engine,
    pipeline,
    microphone_stream,
    service_manager,
    ui_app,
):
    """Backend processing loop — runs in a background thread."""
    logger.info("Backend loop started")

    _report_service_results("initialize", service_manager.initialize_all())
    _report_service_results("start", service_manager.start_all())

    bridge.set_core_state("idle")
    bridge.set_internet_status(True)
    bridge.set_mic_status(True)
    bridge.set_speaker_status(True)
    bridge.set_provider("Ollama")
    bridge.set_model(settings.model)

    logger.info("Backend ready — wake word and text input active")

    try:
        while True:
            # ================================================================
            # Text commands
            # ================================================================
            try:
                command = command_queue.get_nowait()

                if command.casefold() in {"exit", "quit"}:
                    logger.info("Shutdown requested via text command")
                    break
                if command.casefold() == "help":
                    bridge.show_subtitle(
                        "Commands: help, exit | open/close <app> | "
                        "search <q> on <site>"
                    )
                    continue

                if conversation_manager.is_sleep_command(command):
                    if conversation_manager.state == ConversationState.ACTIVE_CONVERSATION:
                        conversation_manager.transition_to_standby(reason="sleep command")
                        bridge.set_core_state("idle")
                        bridge.show_subtitle("Sleeping — wake me with 'JARVIS' or type a command.")
                    else:
                        bridge.show_subtitle("Already in standby mode.")
                    continue

                logger.info("Processing text command: '%s'", command)
                bridge.set_core_state("thinking")
                bridge.set_current_task(command)
                response = brain.process(command)
                bridge.set_current_task("")

                _present_response(bridge, response_manager, response, voice_engine, microphone_stream)

                if getattr(response, "needs_clarification", False):
                    if brain.pending_clarification_exists:
                        bridge.show_subtitle(response.clarification_question or response.message)
                        try:
                            answer = input("> ")
                        except (KeyboardInterrupt, EOFError):
                            answer = ""
                        if answer.strip():
                            bridge.set_core_state("thinking")
                            response = brain.resolve_context(answer.strip())
                            _present_response(bridge, response_manager, response, voice_engine, microphone_stream)
                        else:
                            bridge.show_subtitle("Action cancelled.")
                    elif ("Are you sure" in (response.clarification_question or "")
                          or "confirm" in (response.message or "").casefold()):
                        bridge.show_subtitle(response.clarification_question or "Are you sure?")
                        try:
                            answer = input("> ")
                        except (KeyboardInterrupt, EOFError):
                            answer = ""
                        if answer.strip().casefold() in ("yes", "y", "confirm", "do it", "go ahead"):
                            logger.info("User confirmed, re-processing command")
                            bridge.set_core_state("thinking")
                            response = brain.process(command, confirmed=True)
                            _present_response(bridge, response_manager, response, voice_engine, microphone_stream)
                        else:
                            bridge.show_subtitle("Action cancelled.")

                if conversation_manager.state == ConversationState.STANDBY:
                    conversation_manager.transition_to_active()
                else:
                    conversation_manager.reset_activity()

                bridge.set_core_state("idle")
                continue

            except queue.Empty:
                pass

            # ================================================================
            # Voice commands (state-dependent)
            # ================================================================
            if conversation_manager.state == ConversationState.STANDBY:
                if wake_word_detected.is_set():
                    bridge.wakeActive = True
                    bridge.set_core_state("listening")
                    bridge.show_subtitle("Listening...")

                    command_text = pipeline.wait_for_command(wake_word_detected)

                    bridge.wakeActive = False

                    if command_text:
                        stripped = _strip_wake_word(command_text) or command_text
                        bridge.set_core_state("thinking")
                        bridge.set_current_task(stripped)
                        logger.info("Processing voice command: '%s'", stripped)
                        response = brain.process(stripped)
                        bridge.set_current_task("")

                        _present_response(bridge, response_manager, response, voice_engine, microphone_stream)

                        if getattr(response, "needs_clarification", False):
                            if brain.pending_clarification_exists:
                                bridge.show_subtitle(response.clarification_question or response.message)
                                confirm_result = listener_service.listen_for_command(timeout=8.0)
                                if confirm_result.success and confirm_result.text:
                                    bridge.set_core_state("thinking")
                                    answer = confirm_result.text.strip()
                                    response = brain.resolve_context(answer)
                                    _present_response(bridge, response_manager, response, voice_engine, microphone_stream)
                                else:
                                    bridge.show_subtitle("Action cancelled.")
                            elif "Are you sure" in (response.clarification_question or ""):
                                bridge.show_subtitle(response.clarification_question or "Say 'yes' to confirm.")
                                confirm_result = listener_service.listen_for_command(timeout=5.0)
                                if confirm_result.success and confirm_result.text:
                                    answer = confirm_result.text.strip().casefold()
                                    if answer in ("yes", "y", "confirm", "do it", "go ahead"):
                                        logger.info("Voice confirmation received")
                                        bridge.set_core_state("thinking")
                                        response = brain.process(stripped, confirmed=True)
                                        _present_response(bridge, response_manager, response, voice_engine, microphone_stream)

                        bridge.set_core_state("speaking")
                        conversation_manager.transition_to_active()
                    else:
                        bridge.show_subtitle("Could not understand command.")
                        logger.warning("Voice command failed after all retries")
                        wake_word_service.reset_for_wake()
                        bridge.set_core_state("idle")
                        bridge.show_subtitle("Say 'JARVIS' or type a command.")

            elif conversation_manager.state == ConversationState.ACTIVE_CONVERSATION:
                if conversation_manager.is_expired:
                    conversation_manager.transition_to_standby(reason="timeout")
                    bridge.set_core_state("idle")
                    bridge.show_subtitle("Conversation timed out. Say 'JARVIS' or type a command.")
                    continue

                if voice_engine.is_speaking:
                    logger.info("BARGE-IN: Interrupting speech to listen for next command")
                    voice_engine.interrupt()

                listen_to = min(5.0, max(1.0, conversation_manager.remaining_time))
                logger.info("Listening for command (state=ACTIVE_CONVERSATION, timeout=%.1f)", listen_to)
                bridge.set_core_state("listening")
                bridge.show_subtitle("Listening...")
                result = listener_service.listen_for_command(timeout=listen_to)

                if result.success and result.text:
                    if conversation_manager.is_sleep_command(result.text):
                        bridge.show_subtitle("Sleeping — wake me with 'JARVIS'.")
                        conversation_manager.transition_to_standby(reason="sleep command")
                        bridge.set_core_state("idle")
                        continue

                    stripped = _strip_wake_word(result.text) or result.text
                    bridge.set_core_state("thinking")
                    bridge.set_current_task(stripped)
                    logger.info("Processing conversation command: '%s'", stripped)
                    response = brain.process(stripped)
                    bridge.set_current_task("")

                    _present_response(bridge, response_manager, response, voice_engine, microphone_stream)

                    if getattr(response, "needs_clarification", False):
                        if brain.pending_clarification_exists:
                            bridge.show_subtitle(response.clarification_question or response.message)
                            confirm_result = listener_service.listen_for_command(timeout=8.0)
                            if confirm_result.success and confirm_result.text:
                                bridge.set_core_state("thinking")
                                answer = confirm_result.text.strip()
                                response = brain.resolve_context(answer)
                                _present_response(bridge, response_manager, response, voice_engine, microphone_stream)
                            else:
                                bridge.show_subtitle("Action cancelled.")
                        elif "Are you sure" in (response.clarification_question or ""):
                            bridge.show_subtitle(response.clarification_question or "Say 'yes' to confirm.")
                            confirm_result = listener_service.listen_for_command(timeout=5.0)
                            if confirm_result.success and confirm_result.text:
                                answer = confirm_result.text.strip().casefold()
                                if answer in ("yes", "y", "confirm", "do it", "go ahead"):
                                    logger.info("Voice confirmation received")
                                    bridge.set_core_state("thinking")
                                    response = brain.process(stripped, confirmed=True)
                                    _present_response(bridge, response_manager, response, voice_engine, microphone_stream)

                    bridge.set_core_state("speaking")
                    conversation_manager.reset_activity()
                else:
                    if conversation_manager.is_expired:
                        conversation_manager.transition_to_standby(reason="timeout")
                        bridge.set_core_state("idle")
                        bridge.show_subtitle("Conversation timed out. Say 'JARVIS' or type a command.")

            time.sleep(0.05)

    except Exception as exc:
        _on_backend_error(bridge, microphone_stream, service_manager, exc)
    finally:
        logger.info("Backend loop shutting down")
        try:
            bridge.set_core_state("offline")
        except Exception:
            pass
        _report_service_results("shutdown", service_manager.shutdown_all())
        microphone_stream.shutdown()
        logger.info("Backend shut down")
        try:
            ui_app._quit()
        except Exception:
            pass


def main() -> None:
    # --- Single command mode ---
    if len(sys.argv) > 1:
        parser = Parser()
        planner = Planner()
        registry = Registry()
        response_manager = ResponseManager(debug=DEBUG)
        executor = Executor(registry)
        context_manager = ContextManager()
        task_verifier = TaskVerifier()
        brain = Brain(parser, planner, executor, context_manager=context_manager, task_verifier=task_verifier)
        command = " ".join(sys.argv[1:])
        print(f"Executing single command: '{command}'")
        response = brain.process(command)
        if response.needs_clarification and brain.pending_clarification_exists:
            print(f"\n{response.clarification_question or response.message}")
            answer = input("> ").strip()
            if answer:
                response = brain.resolve_context(answer)
        response_manager.present_console(response)
        return

    # --- Create backend components ---
    parser = Parser()
    planner = Planner()
    registry = Registry()
    response_manager = ResponseManager(debug=DEBUG)
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

    voice_manager = VoiceManager()
    voice_engine = VoiceEngine(
        voice_manager=voice_manager,
        microphone_stream=microphone_stream,
        on_barge_in=lambda: logger.info("BARGE-IN detected in conversation"),
    )
    response_manager._voice_engine = voice_engine

    # Wire VoicePlayer callbacks to mute mic during TTS playback
    # This prevents the echo feedback loop where the assistant's own
    # TTS output is captured by the mic, re-transcribed, and re-processed.
    try:
        player = voice_manager.provider.player
        player.on_playback_started = microphone_stream.mute
        player.on_playback_finished = microphone_stream.unmute
        logger.info("Echo prevention: mic will mute during TTS playback")
    except AttributeError:
        logger.warning(
            "Echo prevention not available: provider does not expose a player"
        )

    def _voice_input() -> str | None:
        if voice_engine.is_speaking:
            logger.info("BARGE-IN: Interrupting speech to listen")
            voice_engine.interrupt()
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
    context_manager = ContextManager()
    task_verifier = TaskVerifier()
    brain = Brain(parser, planner, executor, context_manager=context_manager, task_verifier=task_verifier)

    service_manager = ServiceManager()
    service_manager.register("listener", listener_service)
    service_manager.register("wake_word", wake_word_service)

    pipeline = VoiceConversationPipeline(
        listener_service=listener_service,
        voice_manager=voice_manager,
        microphone_stream=microphone_stream,
        max_retries=3,
        capture_timeout=10.0,
    )

    conversation_manager = ConversationManager(
        wake_word_service=wake_word_service,
        listener_service=listener_service,
        activity_timeout=30.0,
        selection_timeout=30.0,
    )

    # --- Start microphone ---
    logger.info("Starting microphone stream...")
    try:
        microphone_stream.start()
    except Exception as exc:
        logger.warning("Microphone could not be started: %s", exc)

    # --- Create the desktop UI ---
    try:
        ui_app = JarvisApp()
    except Exception as exc:
        logger.critical("Failed to create UI: %s", exc, exc_info=True)
        print(f"ERROR: Could not launch the desktop interface: {exc}")
        print("Falling back to console mode is not supported.")
        sys.exit(1)

    bridge = ui_app.bridge

    # --- Text input thread (stdin for debug) ---
    def _text_input_loop():
        while True:
            try:
                line = input()
            except (KeyboardInterrupt, EOFError):
                command_queue.put("exit")
                break
            line = line.strip()
            if line:
                command_queue.put(line)

    input_thread = threading.Thread(target=_text_input_loop, daemon=True)
    input_thread.start()

    # --- Start backend thread ---
    backend_thread = threading.Thread(
        target=_backend_loop,
        args=(
            bridge,
            command_queue,
            wake_word_detected,
            brain,
            context_manager,
            response_manager,
            listener_service,
            wake_word_service,
            conversation_manager,
            voice_engine,
            pipeline,
            microphone_stream,
            service_manager,
            ui_app,
        ),
        daemon=True,
    )
    backend_thread.start()

    # --- Run the Qt event loop (blocks until UI exits) ---
    logger.info("JARVIS desktop UI starting")
    exit_code = ui_app.run()
    logger.info("UI exited with code %d", exit_code)
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
