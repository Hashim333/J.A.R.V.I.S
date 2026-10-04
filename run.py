"""
run.py — JARVIS application bootstrap.

This module ONLY initializes services and starts the application.  It does
NOT own conversation logic.

The single conversation owner is :class:`services.conversation_owner.
ConversationOwner`, which owns Wake, Listening, Speech Recognition, Intent
Processing, Execution, Speaking and Sleep Mode.  All conversation state
transitions live in exactly one place — the ConversationOwner driving the
:class:`services.conversation_manager.ConversationManager` state machine.
"""
from __future__ import annotations

import logging
import os
from logging.handlers import RotatingFileHandler
from pathlib import Path

# The Whisper/numpy stack pulls in Intel MKL (Fortran runtime), whose
# default console-control handler ABORTS the whole process (forrtl error
# 200) when its hosting console window closes — observed killing a healthy
# backend mid-conversation. Disabling that handler keeps the backend alive;
# Ctrl+C / shutdown paths are unaffected (Python-level handlers remain).
# Must be set before MKL first loads, hence here at module top.
os.environ.setdefault("FOR_DISABLE_CONSOLE_CTRL_HANDLER", "1")

# Qt DPI awareness - MUST be set before any Qt import
# Use Windows DPI awareness v2 (per-monitor DPI aware)
os.environ["QT_QPA_PLATFORM"] = "windows:dpiawareness=2"
os.environ["QT_AUTO_SCREEN_SCALE_FACTOR"] = "1"
os.environ["QT_ENABLE_HIGHDPI_SCALING"] = "1"

import queue
import sys
import threading
import time

from config.settings import settings
from brain import Brain
from brain.parser import Parser
from brain.planner import Planner
from context_manager.context_manager import ContextManager
from executor.executor import Executor
from verification.task_verifier import TaskVerifier
from automation.registry import Registry
from automation.handlers import AppsHandler, BrowserHandler, MouseHandler, KeyboardHandler, FileManagerHandler
from automation.browser_service import stop_browser_service
from tasks.task_manager import TaskManager
from intelligence.world_state import WorldStateService
from world_model import WorldModel
from system_awareness import SystemAwarenessService
from response.manager import ResponseManager
from thinking.reasoner import Reasoner
from working_memory import WorkingMemory
from skills.manager import SkillManager
from services import (
    ServiceManager, WakeWordService,
    ConversationManager, ShutdownManager,
)
from services.conversation_owner import ConversationOwner
from voice.microphone_stream import MicrophoneStream
from voice.microphone_processor import MicrophoneProcessor
from voice.duplex import DuplexVoiceSession
from voice.whisper_stt import preload_model
from voice.manager import VoiceManager
from voice.engine import VoiceEngine
from ui.app import ACTIVATION_SERVER_NAME, JarvisApp
from services.instance_guard import InstanceGuard
from monitoring.watchdog import WatchdogManager
from monitoring.instrumentation import (
    install as install_diag,
    register_queue,
)

_LOG_FILE = Path(__file__).resolve().parent / "logs" / "jarvis.log"
_LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
    handlers=[
        logging.StreamHandler(),
        RotatingFileHandler(
            _LOG_FILE, maxBytes=5 * 1024 * 1024, backupCount=5, encoding="utf-8",
        ),
    ],
)
logger = logging.getLogger("run")
logging.getLogger("voice.microphone_stream").setLevel(logging.WARNING)

DEBUG = settings.debug
_INSTANCE_GUARD: InstanceGuard | None = None
_INSTANCE_MUTEX_NAME = r"Local\MONDAY.DesktopAssistant"

# Automatic Sleep: the conversation stays engaged for follow-ups and only
# returns to Wake Mode after this many seconds of true silence (Requirement
# #9).  A pending confirmation is still "conversation", so the confirmation
# timeout is deliberately shorter.
_CONVERSATION_AUTO_SLEEP_SECONDS = 30.0
_CONVERSATION_CONFIRMATION_TIMEOUT_SECONDS = 15.0


def _ensure_single_backend() -> bool:
    """Acquire the process mutex; a duplicate launch asks the UI to show."""
    global _INSTANCE_GUARD
    guard = InstanceGuard(
        Path(__file__).resolve().parent,
        _INSTANCE_MUTEX_NAME,
    )
    if not guard.acquire():
        if not InstanceGuard.notify_primary(ACTIVATION_SERVER_NAME):
            logger.warning("An existing JARVIS process owns the instance mutex")
        return False
    _INSTANCE_GUARD = guard
    return True


def _release_backend_pid_file() -> None:
    """Release the mutex and remove this process's diagnostic PID file."""
    global _INSTANCE_GUARD
    if _INSTANCE_GUARD is not None:
        _INSTANCE_GUARD.release()
        _INSTANCE_GUARD = None


def main() -> None:
    autostart = "--autostart" in sys.argv[1:]
    sys.argv = [arg for arg in sys.argv if arg != "--autostart"]
    backend_only = any(arg in {"--backend-only", "--headless", "--no-ui"} for arg in sys.argv[1:])
    if backend_only:
        sys.argv = [arg for arg in sys.argv if arg not in {"--backend-only", "--headless", "--no-ui"}]
        sys.argv = [sys.argv[0]] + [arg for arg in sys.argv[1:] if arg not in {"--backend-only", "--headless", "--no-ui"}]

# Persistent modes open the microphone: exactly one backend may run.
    # (One-shot CLI text mode below never touches audio — no guard needed.)
    if len(sys.argv) == 1 and not _ensure_single_backend():
        return

    if len(sys.argv) > 1:
        parser = Parser()
        planner = Planner()
        registry = Registry()

        voice_manager = VoiceManager()
        voice_engine = VoiceEngine(voice_manager=voice_manager)
        response_manager = ResponseManager(debug=DEBUG, voice_engine=voice_engine)

        executor = Executor(registry)
        context_manager = ContextManager()
        task_verifier = TaskVerifier()
        world_model = WorldModel()
        world_state = WorldStateService(world_model=world_model, context_manager=context_manager)
        world_state.start()
        system_awareness = SystemAwarenessService(world_model=world_model)
        system_awareness.start()
        working_memory = WorkingMemory()
        working_memory.start()
        reasoner = Reasoner()
        skill_manager = SkillManager()
        brain = Brain(parser, planner, executor, context_manager=context_manager,
                      task_verifier=task_verifier, world_state=world_state,
                      reasoner=reasoner, working_memory=working_memory,
                      system_awareness=system_awareness,
                      skill_manager=skill_manager)
        command = " ".join(sys.argv[1:])
        print(f"Executing: '{command}'")
        response = brain.process(command)
        if response.needs_clarification and brain.pending_clarification_exists:
            print(f"\n{response.clarification_question or response.message}")
            answer = input("> ").strip()
            if answer:
                response = brain.resolve_context(answer)
        system_awareness.stop()
        world_state.stop()
        working_memory.stop()
        response_manager.present_console(response)
        return

    parser = Parser()
    planner = Planner()
    registry = Registry()

    context_manager = ContextManager()
    world_model = WorldModel()
    world_state = WorldStateService(world_model=world_model, context_manager=context_manager)
    system_awareness = SystemAwarenessService(world_model=world_model)

    microphone_stream = MicrophoneStream(chunk_size=1024, sample_rate=16000)

    voice_manager = VoiceManager()
    voice_engine = VoiceEngine(
        voice_manager=voice_manager,
        microphone_stream=microphone_stream,
        on_barge_in=lambda: logger.info("Barge-in detected"),
    )

    response_manager = ResponseManager(debug=DEBUG, voice_engine=voice_engine)

    command_queue = queue.Queue()
    wake_word_detected = threading.Event()

    register_queue("command_queue", command_queue)

    wake_word_service = WakeWordService(
        wake_word_detected_event=wake_word_detected,
        microphone_stream=microphone_stream,
    )
    register_queue("tts_queue", lambda: voice_manager.queue_size)

    # ── Full-duplex voice session ────────────────────────────────────
    # Owns the single microphone consumer and routes every chunk through
    # echo cancellation -> adaptive noise suppression -> wake / capture /
    # barge-in VADs and streaming STT.
    duplex_session = DuplexVoiceSession(sample_rate=16000)

    # Warm the shared Faster-Whisper model on a background thread so the first
    # capture is never stalled by the one-time model download/load.
    preload_model()

    def _on_barge_in() -> None:
        """User interrupted JARVIS's speech — stop TTS and get ready to hear them."""
        logger.info("Barge-in: user interrupted speech")
        try:
            voice_engine.interrupt(reason="duplex_barge_in")
        except Exception as exc:
            logger.error("Barge-in interrupt failed: %s", exc, exc_info=True)

    duplex_session.on_barge_in = _on_barge_in
    wake_word_service.set_session(duplex_session)
    voice_engine.set_duplex_session(duplex_session)

    try:
        player = voice_manager.provider.player
    except AttributeError:
        player = None
    if player is not None and hasattr(player, "on_chunk_written"):
        # Full-duplex echo cancellation: feed back the exact PCM written to
        # the speakers so JARVIS's own voice is cancelled from the mic.  This
        # replaces mic-mute, which would block instant barge-in.
        player.on_chunk_written = duplex_session.feed_playback_reference
        logger.info("Full-duplex echo cancellation active (playback reference fed)")
    else:
        logger.info("Echo prevention active (mic-mute fallback, no PCM reference)")

    def _tts_mute_guard_start() -> None:
        """Mute the mic while TTS plays — but ONLY when no echo-cancelling
        playback reference is available for the CURRENT provider.

        The active provider can change at runtime (ElevenLabs quota ->
        Piper -> system SAPI fallback), so this is decided per utterance,
        not once at startup: providers whose player feeds the echo
        canceller keep the mic open for instant barge-in; every other
        provider mutes (ownership-safe "tts" owner) so JARVIS's own voice
        can never self-trigger barge-in or phantom captures.
        """
        try:
            provider = voice_manager.provider
            provider_player = getattr(provider, "player", None)
            if (
                provider_player is not None
                and getattr(provider_player, "on_chunk_written", None) is not None
            ):
                return
        except Exception:
            pass
        microphone_stream.mute("tts")

    def _tts_mute_guard_end() -> None:
        """Re-arm the mic after TTS (releases only the "tts" mute owner)."""
        try:
            microphone_stream.unmute("tts")
        except Exception as exc:
            logger.error("TTS mute-guard release failed: %s", exc)

    # Provider-agnostic, utterance-scoped, always paired (try/finally in
    # the speech worker): the mic can never be left muted by TTS, and a
    # runtime provider swap can never leave it unguarded.
    voice_manager.on_utterance_started = _tts_mute_guard_start
    voice_manager.on_utterance_finished = _tts_mute_guard_end

    def _voice_input() -> str | None:
        if voice_engine.is_speaking:
            voice_engine.interrupt()
        result = duplex_session.capture_command(timeout=15.0)
        return result.text if result.success else None

    apps_handler = AppsHandler(engine=voice_engine)
    mouse_handler = MouseHandler()
    keyboard_handler = KeyboardHandler()
    browser_handler = BrowserHandler()
    file_manager_handler = FileManagerHandler(engine=voice_engine)
    registry.register("open_app", apps_handler)
    registry.register("close_app", apps_handler)
    registry.register("open_website", browser_handler)
    registry.register("search", browser_handler)
    registry.register("click_first_video", browser_handler)
    registry.register("youtube_state", browser_handler)
    registry.register("youtube_pause", browser_handler)
    registry.register("youtube_resume", browser_handler)
    registry.register("youtube_play_next", browser_handler)
    registry.register("youtube_play_previous", browser_handler)
    registry.register("youtube_skip_ad", browser_handler)
    registry.register("youtube_like", browser_handler)
    registry.register("youtube_subscribe", browser_handler)
    registry.register("youtube_continue_watching", browser_handler)
    registry.register("youtube_volume_up", browser_handler)
    registry.register("youtube_volume_down", browser_handler)
    registry.register("youtube_mute", browser_handler)
    registry.register("youtube_unmute", browser_handler)
    registry.register("youtube_enter_fullscreen", browser_handler)
    registry.register("youtube_exit_fullscreen", browser_handler)
    registry.register("youtube_replay", browser_handler)
    registry.register("youtube_go_back", browser_handler)
    registry.register("scroll_page", browser_handler)
    registry.register("get_page_state", browser_handler)
    registry.register("get_selected_text", browser_handler)
    registry.register("move_mouse", mouse_handler)
    registry.register("left_click", mouse_handler)
    registry.register("right_click", mouse_handler)
    registry.register("double_click", mouse_handler)
    registry.register("scroll", mouse_handler)
    registry.register("type_text", keyboard_handler)
    registry.register("hotkey", keyboard_handler)

    # File manager actions
    for action in (
        "open_file",
        "find_file",
        "open_file_location",
        "copy_file",
        "move_file",
        "rename_file",
        "delete_file",
    ):
        registry.register(action, file_manager_handler)

    executor = Executor(registry, voice_input=_voice_input)
    task_verifier = TaskVerifier()
    working_memory = WorkingMemory()
    working_memory.start()
    reasoner = Reasoner()
    skill_manager = SkillManager()
    brain = Brain(parser, planner, executor, context_manager=context_manager,
                  task_verifier=task_verifier, world_state=world_state,
                  reasoner=reasoner, working_memory=working_memory,
                  system_awareness=system_awareness,
                  skill_manager=skill_manager)

    service_manager = ServiceManager()
    service_manager.register("wake_word", wake_word_service)

    world_state.start()
    system_awareness.start()
    logger.info("World state service started")
    logger.info("System awareness service started")

    conversation_manager = ConversationManager(
        activity_timeout=_CONVERSATION_AUTO_SLEEP_SECONDS,
        confirmation_timeout=_CONVERSATION_CONFIRMATION_TIMEOUT_SECONDS,
        wake_word_service=wake_word_service,
    )

    shutdown_manager = ShutdownManager()
    task_manager = TaskManager(default_deadline=30.0)

    # Route the continuous mic feed into the full-duplex session (wake word,
    # capture, and barge-in all consume the echo-cancelled, denoised signal).
    microphone_stream.set_consumer(duplex_session.process_chunk)

    # Wire the configured AGC / noise gate / sensitivity / normalization into
    # the live pipeline.  The processor's start()/shutdown() follow the
    # stream lifecycle automatically (microphone_stream.start()/shutdown()).
    microphone_stream.set_processor(
        MicrophoneProcessor(
            sample_rate=16000,
            sensitivity=settings.mic_sensitivity,
            agc_enabled=settings.mic_agc_enabled,
            agc_target_level=settings.mic_agc_target_level,
            noise_gate_enabled=settings.mic_noise_gate_enabled,
            noise_gate_threshold=settings.mic_noise_gate_threshold,
            dc_removal_enabled=settings.mic_dc_removal_enabled,
            high_pass_enabled=settings.mic_high_pass_enabled,
            high_pass_cutoff_hz=settings.mic_high_pass_cutoff_hz,
            speech_normalization_enabled=settings.mic_speech_normalization_enabled,
        )
    )
    logger.info(
        "MicrophoneProcessor wired: sensitivity=%s agc=%s target=%.3f "
        "noise_gate=%s threshold=%.3f dc=%s hp=%s(%.0f Hz) speech_norm=%s",
        settings.mic_sensitivity,
        settings.mic_agc_enabled,
        settings.mic_agc_target_level,
        settings.mic_noise_gate_enabled,
        settings.mic_noise_gate_threshold,
        settings.mic_dc_removal_enabled,
        settings.mic_high_pass_enabled,
        settings.mic_high_pass_cutoff_hz,
        settings.mic_speech_normalization_enabled,
    )

    logger.info("Starting microphone...")
    try:
        microphone_stream.start()
    except Exception as exc:
        logger.warning("Microphone could not be started: %s", exc)

    ui_app = None
    try:
        if backend_only:
            from PySide6.QtWidgets import QApplication
            app = QApplication.instance() or QApplication(sys.argv)
            app.setQuitOnLastWindowClosed(False)
            from ui.bridge import Bridge
            bridge = Bridge()
            logger.info("JARVIS backend-only mode started; UI disabled")
        else:
            ui_app = JarvisApp(start_minimized=autostart)
            bridge = ui_app.bridge
    except Exception as exc:
        logger.critical("Failed to create UI/backend bridge: %s", exc, exc_info=True)
        print(f"ERROR: Could not launch JARVIS: {exc}")
        sys.exit(1)

    if ui_app is not None:
        install_diag()

    watchdog_manager = WatchdogManager()
    shutdown_event = threading.Event()
    _shutdown_in_progress = threading.Event()

    # ── The single conversation owner ────────────────────────────────
    # Owns Wake, Listening, Speech Recognition, Intent Processing,
    # Execution, Speaking and Sleep Mode.  run.py does NOT own any
    # conversation logic.
    conversation_owner = ConversationOwner(
        conversation_manager=conversation_manager,
        bridge=bridge,
        brain=brain,
        task_manager=task_manager,
        response_manager=response_manager,
        voice_engine=voice_engine,
        wake_word_service=wake_word_service,
        microphone_stream=microphone_stream,
        duplex_session=duplex_session,
        command_queue=command_queue,
        wake_word_detected=wake_word_detected,
        watchdog_manager=watchdog_manager,
        service_manager=service_manager,
        shutdown_in_progress=_shutdown_in_progress,
        shutdown_event=shutdown_event,
        # The production default is passive MONDAY wake-word activation.
        # The setting remains the single future switch for continuous mode.
        wake_word_enabled=settings.wake_word_enabled,
    )

    def _text_input_loop():
        while True:
            try:
                line = input()
            except KeyboardInterrupt:
                # Explicit user interrupt (Ctrl+C) — a deliberate shutdown.
                _shutdown_in_progress.set()
                command_queue.put("exit")
                break
            except EOFError:
                # FIX-VOICE-RUNTIME-001: a closed/failed stdin is NOT a user
                # shutdown request and must never terminate JARVIS.  Stop
                # reading text commands and keep the voice/wake path alive.
                logger.info(
                    "Text input closed — text commands disabled; voice still active"
                )
                break
            line = line.strip()
            if line:
                from brain.intent_normalizer import Intent, normalize as normalize_intent
                if normalize_intent(line) == Intent.EXIT:
                    _shutdown_in_progress.set()
                command_queue.put(line)

    input_thread = threading.Thread(target=_text_input_loop, daemon=True)
    input_thread.start()

    backend_thread = threading.Thread(
        target=conversation_owner.run,
        daemon=True,
    )
    backend_thread.start()
    shutdown_manager.register_thread(backend_thread)
    shutdown_manager.register_thread(backend_thread)

    # ── Shutdown hooks ────────────────────────────────────────────────
    # Stopped in bounded phases so resources are released even if a
    # component misbehaves during exit.
    shutdown_manager.on("stop_wake_word", wake_word_service.stop)
    shutdown_manager.on("stop_conversation", voice_engine.cancel_all)
    shutdown_manager.on("stop_system_awareness", system_awareness.stop)
    shutdown_manager.on("stop_world_state", world_state.stop)
    shutdown_manager.on("stop_working_memory", working_memory.stop)
    shutdown_manager.on("stop_watchdogs", watchdog_manager.stop_all)
    shutdown_manager.on(
        "stop_browser",
        lambda: stop_browser_service(force=False),
    )
    shutdown_manager.on(
        "join_worker_threads", lambda: voice_engine.shutdown(),
    )

    def _signal_backend_shutdown():
        """Signal the owner loop to exit by posting an EXIT command."""
        if _shutdown_in_progress.is_set():
            return
        _shutdown_in_progress.set()
        command_queue.put("exit")
        logger.debug("Backend shutdown signaled")

    shutdown_manager.on("stop_listening", _signal_backend_shutdown)
    shutdown_manager.on("stop_listening", microphone_stream.shutdown)

    # Bounded shutdown runs on a worker thread so the GUI thread is never
    # blocked for the full multi-phase teardown (which would show the window
    # as "Not Responding" during exit).  main() joins it after the event loop.
    shutdown_thread: threading.Thread | None = None

    def _run_bounded_shutdown():
        try:
            shutdown_manager.shutdown()
        except Exception as exc:
            logger.error("Shutdown worker failed: %s", exc, exc_info=True)

    def _on_about_to_quit():
        """UI is closing; signal backend teardown before the event loop exits."""
        nonlocal shutdown_thread
        logger.info("UI closing — beginning bounded backend shutdown")
        _signal_backend_shutdown()
        try:
            task_manager.cancel_active("ui shutdown")
        except Exception as exc:
            logger.error("UI shutdown task cancel failed: %s", exc)
        try:
            brain.cancel_current()
        except Exception as exc:
            logger.error("Brain cancel on UI shutdown failed: %s", exc)
        if shutdown_thread is None or not shutdown_thread.is_alive():
            shutdown_thread = threading.Thread(
                target=_run_bounded_shutdown,
                name="shutdown-worker",
                daemon=True,
            )
            shutdown_thread.start()

    if ui_app is not None:
        ui_app.app.aboutToQuit.connect(_on_about_to_quit)

    if backend_only:
        logger.info("JARVIS backend-only mode started; waiting for shutdown signal")
        try:
            while not _shutdown_in_progress.is_set():
                time.sleep(0.5)
        except KeyboardInterrupt:
            logger.info("Backend-only run interrupted by Ctrl+C")
            _shutdown_in_progress.set()
            command_queue.put("exit")

        logger.info("Backend-only run exiting")
        shutdown_event.set()
        shutdown_manager.shutdown()
        watchdog_manager.stop_all()
        _release_backend_pid_file()
        sys.exit(0)

    logger.info("JARVIS desktop UI starting")
    exit_code = ui_app.run()
    logger.info("UI exited with code %d", exit_code)
    shutdown_event.set()
    if shutdown_thread is not None and shutdown_thread.is_alive():
        shutdown_thread.join(timeout=12.0)
    watchdog_manager.stop_all()
    _release_backend_pid_file()
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
