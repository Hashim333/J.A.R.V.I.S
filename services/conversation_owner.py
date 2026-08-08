"""
services/conversation_owner.py

The SINGLE conversation owner for JARVIS.

This class owns the entire conversation lifecycle:

    Wake -> Listening -> Speech Recognition -> Intent Processing
         -> Execution -> Speaking -> Sleep Mode

Every conversation state transition flows through the one state machine
(:class:`services.conversation_manager.ConversationManager`) and is driven
from exactly one place — this owner.  All other modules are helpers:

    * voice modules only capture audio (they never decide conversation state)
    * TTS only speaks (it never changes conversation state)
    * automation only executes actions (it never changes conversation state)
    * brain only reasons (it never changes conversation state)

``run.py`` is an application bootstrap only: it builds the components,
starts this owner on a background thread, and handles shutdown.
"""
from __future__ import annotations

import logging
import queue
import re
import threading
import time

from brain.intent_normalizer import Intent, normalize as normalize_intent
from monitoring.instrumentation import Timer
from monitoring.pipeline_trace import (
    set_trace_state as _set_trace_state,
    stage_entry as _stage_entry,
    stage_exit as _stage_exit,
)
from services.conversation_manager import ConversationManager, ConversationState
from voice.duplex import CaptureResult

logger = logging.getLogger(__name__)

_BACKEND_LOOP_SLEEP = 0.05
_BACKEND_QUEUE_TIMEOUT = 0.1
_BACKEND_WATCHDOG_TIMEOUT = 60.0
_CONVERSATION_WATCHDOG_TIMEOUT = 90.0
_MAX_CONSECUTIVE_FAILED_LISTENS = 3
_CONVERSATION_AUTO_SLEEP_SECONDS = 30.0
_CONVERSATION_CONFIRMATION_TIMEOUT_SECONDS = 15.0
_WAKE_IDLE_TIMEOUT_SECONDS = 30.0
_MAX_WAKE_NO_SPEECH_ROUNDS = 5

_WAKE_PHRASE = "jarvis"
_WAKE_PATTERN = re.compile(rf'\b{re.escape(_WAKE_PHRASE)}\b', re.IGNORECASE)


class ConversationOwner:
    """The single conversation owner.

    Owns Wake, Listening, Speech Recognition, Intent Processing, Execution,
    Speaking and Sleep Mode.  All conversation state transitions are driven
    through the injected :class:`ConversationManager` state machine — no
    other module may change conversation state.
    """

    def __init__(
        self,
        *,
        conversation_manager: ConversationManager,
        bridge,
        brain,
        task_manager,
        response_manager,
        voice_engine,
        wake_word_service,
        microphone_stream,
        duplex_session,
        command_queue,
        wake_word_detected: threading.Event,
        watchdog_manager,
        service_manager,
        shutdown_in_progress: threading.Event,
        shutdown_event: threading.Event,
    ) -> None:
        self._conversation_manager = conversation_manager
        self._bridge = bridge
        self._brain = brain
        self._task_manager = task_manager
        self._response_manager = response_manager
        self._voice_engine = voice_engine
        self._wake_word_service = wake_word_service
        self._microphone_stream = microphone_stream
        self._duplex_session = duplex_session
        self._command_queue = command_queue
        self._wake_word_detected = wake_word_detected
        self._watchdog_manager = watchdog_manager
        self._service_manager = service_manager
        self._shutdown_in_progress = shutdown_in_progress
        self._shutdown_event = shutdown_event

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def run(self) -> None:
        """Run the conversation loop (blocking).  Call on a background thread."""
        logger.info("Conversation owner loop started")
        svc_results = self._service_manager.initialize_all()
        failures = {n: o for n, o in svc_results.items() if o != "ok"}
        if failures:
            logger.warning("Service init issues: %s", failures)
        svc_results = self._service_manager.start_all()
        failures = {n: o for n, o in svc_results.items() if o != "ok"}
        if failures:
            logger.warning("Service start issues: %s", failures)

        bridge = self._bridge
        bridge.set_core_state("idle")
        bridge.set_internet_status(True)
        bridge.set_mic_status(True)
        bridge.set_speaker_status(True)
        from config.settings import settings
        bridge.set_provider("Ollama")
        bridge.set_model(settings.model)

        # The wake-word path only runs while the conversation state is IDLE.
        # The manager defaults to STANDBY, so arm it explicitly or the wake
        # word never triggers on a fresh start.
        self._conversation_manager.return_to_idle("backend ready")

        def _trace_state() -> dict[str, str]:
            try:
                conv = (
                    self._conversation_manager.state.value
                    if hasattr(self._conversation_manager.state, "value")
                    else str(self._conversation_manager.state)
                )
                return {"conversation": conv, "ui": bridge._core_state}
            except Exception:
                return {"conversation": "?", "ui": "?"}

        _set_trace_state(_trace_state)

        self._watchdog_manager.add(
            "backend_loop",
            timeout=_BACKEND_WATCHDOG_TIMEOUT,
            on_stall=self._on_backend_stall,
        )
        self._watchdog_manager.add(
            "conversation",
            timeout=_CONVERSATION_WATCHDOG_TIMEOUT,
            on_stall=self._on_conversation_stall,
        )

        logger.info("Conversation owner ready")
        consecutive_failed_listens = 0

        try:
            while True:
                if self._shutdown_in_progress.is_set():
                    logger.info("Conversation owner shutdown requested — exiting loop")
                    break
                bridge.set_backend_heartbeat()
                self._watchdog_manager.kick("backend_loop")
                self._watchdog_manager.kick("conversation")

                # ── Check for expired confirmation ──
                if (
                    self._conversation_manager.has_pending_confirmation
                    and self._conversation_manager.is_expired
                ):
                    logger.info("Confirmation expired — discarding stored plan")
                    self._conversation_manager.on_timeout()

                # ── Time out any task that outlived its deadline ──
                expired_tasks = self._task_manager.check_timeouts()
                if expired_tasks:
                    for expired in expired_tasks:
                        logger.warning(
                            "Task %s expired (deadline) — marked FAILED",
                            expired.task_id,
                        )

                # ============================================================
                # Text commands (blocking wait with timeout)
                # ============================================================
                try:
                    command = self._command_queue.get(timeout=_BACKEND_QUEUE_TIMEOUT)

                    if normalize_intent(command) == Intent.EXIT:
                        logger.info("Shutdown via text command")
                        break

                    if self._shutdown_in_progress.is_set():
                        logger.info("Shutdown requested — skipping queued command")
                        break

                    self._brain.cancel_current()

                    if normalize_intent(command) == Intent.HELP:
                        bridge.show_subtitle(
                            "Commands: help, exit | open/close <app> | "
                            "search <q> on <site>"
                        )
                        continue

                    if self._conversation_manager.is_exit_command(command):
                        bridge.show_subtitle(
                            "Ending conversation. Say 'JARVIS' or type a command."
                        )
                        self._conversation_manager.return_to_idle("exit command")
                        bridge.set_core_state("idle")
                        continue

                    # ── Check pending confirmation BEFORE processing ──
                    if self._check_pending_confirmation(command):
                        continue

                    logger.info("Processing text: '%s'", command)
                    logger.info("Recognized text: %r", command)
                    bridge.add_conversation_entry("USER", command)
                    self._run_command(command)
                    if self._conversation_manager.has_pending_confirmation:
                        self._conversation_manager.reset_activity()
                    else:
                        self._conversation_manager.transition_to_active(
                            "command complete"
                        )
                    continue

                except queue.Empty:
                    pass

                # ============================================================
                # Voice (wake-word)
                # ============================================================
                if self._conversation_manager.state in (ConversationState.IDLE,):
                    if self._wake_word_detected.is_set():
                        wake_start = _stage_entry("backend.wake_command")
                        self._wake_word_detected.clear()
                        self._brain.cancel_current()
                        self._conversation_manager.on_wake_word()
                        bridge.wakeActive = True
                        bridge.set_core_state("listening")
                        bridge.show_subtitle("Listening...")

                        self._watchdog_manager.kick("backend_loop")
                        self._watchdog_manager.kick("conversation")
                        # Confirm aloud ("Yes?") WITHOUT muting the mic: the echo
                        # canceller removes JARVIS's own voice from the capture, so
                        # the user can start speaking the moment they hear it — the
                        # first word is recovered from the pre-roll buffer.
                        try:
                            self._voice_engine.speak("Yes?")
                        except Exception:
                            pass
                        # Let the short prompt finish so JARVIS never hears its own
                        # "Yes?" as the start of the command.
                        self._wait_for_speech_end(timeout=6.0)

                        # ── Wake-to-command listen loop (Req #1/#2/#3) ──
                        handled = False
                        no_speech_rounds = 0
                        while not handled:
                            if self._shutdown_in_progress.is_set():
                                handled = True
                                break
                            # Never starve queued text commands during a long wait.
                            if self._command_queue.qsize() > 0:
                                handled = True
                                break
                            self._watchdog_manager.kick("backend_loop")
                            self._watchdog_manager.kick("conversation")
                            bridge.set_core_state("listening")
                            bridge.wakeActive = True
                            bridge.show_subtitle("Listening...")
                            try:
                                with Timer("capture_command"):
                                    result = self._duplex_session.capture_command(
                                        timeout=_WAKE_IDLE_TIMEOUT_SECONDS,
                                        on_partial=lambda text: bridge.show_subtitle(text),
                                    )
                            except Exception as exc:
                                logger.error(
                                    "Voice capture failed: %s", exc, exc_info=True
                                )
                                result = CaptureResult(
                                    "", 0.0, False, reason="capture_error"
                                )
                            bridge.wakeActive = False
                            # Safety: never leave the mic muted after capture.
                            self._microphone_stream.unmute()

                            if result.success and result.text:
                                command_text = result.text.strip()
                                stripped = (
                                    self._strip_wake_word(command_text) or command_text
                                )

                                if self._conversation_manager.is_exit_command(stripped):
                                    bridge.show_subtitle("Ending conversation.")
                                    self._speak_with_retry("Goodbye.")
                                    self._wait_for_speech_end(timeout=10.0)
                                    self._conversation_manager.return_to_idle(
                                        "exit command"
                                    )
                                    bridge.set_core_state("idle")
                                    _stage_exit(
                                        "backend.wake_command", wake_start, status="EXIT"
                                    )
                                    handled = True
                                    break

                                # ── Check pending confirmation BEFORE processing ──
                                if self._check_pending_confirmation(stripped):
                                    _stage_exit(
                                        "backend.wake_command",
                                        wake_start,
                                        status="CONFIRMATION",
                                    )
                                    handled = True
                                    break

                                bridge.add_conversation_entry("USER", stripped)
                                logger.info(
                                    "Recognized text: %r (confidence=%.3f)",
                                    stripped, result.confidence,
                                )
                                logger.info(
                                    "Processing voice: '%s' (speech confidence=%.3f)",
                                    stripped, result.confidence,
                                )
                                self._run_command(
                                    stripped,
                                    speech_confidence=result.confidence,
                                    speech_recognition_ms=result.recognition_ms,
                                )
                                # Requirement #9: stay engaged for follow-ups instead
                                # of dropping straight back to wake mode.
                                if self._conversation_manager.has_pending_confirmation:
                                    self._conversation_manager.reset_activity()
                                else:
                                    self._conversation_manager.transition_to_active(
                                        "command complete"
                                    )
                                _stage_exit(
                                    "backend.wake_command", wake_start, status="OK"
                                )
                                handled = True
                                break

                            # ── Capture failed: respond and KEEP LISTENING ──
                            reason = result.reason or ""
                            text = (result.text or "").strip()

                            if reason == "no_speech":
                                no_speech_rounds += 1
                                logger.info(
                                    "WAKE_CAPTURE no speech after %.0fs (round %d) — prompting",
                                    _WAKE_IDLE_TIMEOUT_SECONDS, no_speech_rounds,
                                )
                                if no_speech_rounds >= _MAX_WAKE_NO_SPEECH_ROUNDS:
                                    bridge.show_subtitle(
                                        "I'll be here. Say 'JARVIS' when you need me."
                                    )
                                    self._speak_with_retry(
                                        "I'll be here. Say JARVIS when you need me."
                                    )
                                    self._wait_for_speech_end(timeout=10.0)
                                    self._conversation_manager.return_to_idle(
                                        "no speech"
                                    )
                                    bridge.set_core_state("idle")
                                    _stage_exit(
                                        "backend.wake_command",
                                        wake_start,
                                        status="NO_SPEECH",
                                    )
                                    handled = True
                                    break
                                # Requirement #3: say "I'm still listening." and stay
                                # listening — never exit just because the timer ran out.
                                bridge.show_subtitle("I'm still listening.")
                                self._speak_with_retry("I'm still listening.")
                                self._wait_for_speech_end(timeout=10.0)
                                continue

                            if not text:
                                # Requirement #8: empty recognition is never NO_COMMAND.
                                logger.info(
                                    "WAKE_CAPTURE empty recognition — asking to repeat"
                                )
                                bridge.show_subtitle("I didn't catch that.")
                                self._speak_with_retry("I didn't catch that.")
                                self._wait_for_speech_end(timeout=10.0)
                                continue

                            if reason == "low confidence":
                                # Requirement #6: never execute a low-confidence command.
                                logger.info(
                                    "WAKE_CAPTURE low confidence (%.3f) — asking to repeat",
                                    result.confidence,
                                )
                                bridge.show_subtitle(
                                    "Sorry sir, could you repeat that?"
                                )
                                self._speak_with_retry(
                                    "Sorry sir, could you repeat that?"
                                )
                                self._wait_for_speech_end(timeout=10.0)
                                continue

                            # Requirement #7: partial words / other rejections.
                            logger.info(
                                "WAKE_CAPTURE rejected (%s) — asking to repeat", reason
                            )
                            bridge.show_subtitle(
                                "I didn't catch that. Could you repeat it?"
                            )
                            self._speak_with_retry(
                                "I didn't catch that. Could you repeat it?"
                            )
                            self._wait_for_speech_end(timeout=10.0)
                            continue

                # ============================================================
                # Voice (active conversation / awaiting confirmation)
                # ============================================================
                elif self._conversation_manager.state in (
                    ConversationState.ACTIVE_CONVERSATION,
                    ConversationState.WAITING_CONFIRMATION,
                ):
                    if self._shutdown_in_progress.is_set():
                        continue

                    if self._command_queue.qsize() > 0:
                        logger.debug(
                            "Queued commands pending (%d) — skipping voice listen",
                            self._command_queue.qsize(),
                        )
                        continue

                    # Expiry is only judged once JARVIS has actually finished
                    # speaking — a long TTS response must never look like silence.
                    if (
                        self._voice_engine.is_speaking
                        or self._voice_engine.queue_size > 0
                    ):
                        self._voice_engine.start_barge_in()
                        time.sleep(0.05)
                        continue

                    self._voice_engine.stop_barge_in()

                    if self._conversation_manager.is_expired:
                        logger.info(
                            "Conversation timed out after %.0fs",
                            self._conversation_manager._activity_timeout,
                        )
                        self._conversation_manager.on_timeout()
                        bridge.set_core_state("idle")
                        bridge.show_subtitle(
                            "Conversation timed out. Say 'JARVIS' or type a command."
                        )
                        self._voice_engine.stop_barge_in()
                        continue

                    # A fresh 30 s of true silence starts now that JARVIS has
                    # finished speaking (Requirement #9).
                    self._conversation_manager.reset_activity()
                    listen_to = min(
                        _CONVERSATION_AUTO_SLEEP_SECONDS,
                        max(1.0, self._conversation_manager.remaining_time),
                    )
                    bridge.set_core_state("listening")
                    bridge.show_subtitle("Listening...")
                    active_start = _stage_entry("backend.conversation_listen")
                    try:
                        with Timer("capture_command"):
                            result = self._duplex_session.capture_command(
                                timeout=listen_to,
                                on_partial=lambda text: bridge.show_subtitle(text),
                            )
                    except Exception as exc:
                        logger.error("Listen failed: %s", exc)
                        bridge.show_subtitle("Could not listen. Please try again.")
                        self._microphone_stream.unmute()
                        _stage_exit(
                            "backend.conversation_listen", active_start, status="FAIL"
                        )
                        time.sleep(0.5)
                        continue
                    self._microphone_stream.unmute()
                    _stage_exit(
                        "backend.conversation_listen", active_start, status="OK"
                    )

                    if result.success and result.text:
                        text = result.text.strip()
                        consecutive_failed_listens = 0

                        if self._conversation_manager.is_exit_command(text):
                            bridge.show_subtitle("Ending conversation.")
                            self._speak_with_retry("Goodbye.")
                            self._wait_for_speech_end(timeout=10.0)
                            self._conversation_manager.return_to_idle("exit command")
                            bridge.set_core_state("idle")
                            continue

                        stripped = self._strip_wake_word(text) or text

                        # ── Check pending confirmation BEFORE processing ──
                        if self._check_pending_confirmation(stripped):
                            self._conversation_manager.reset_activity()
                            continue

                        bridge.add_conversation_entry("USER", stripped)
                        logger.info(
                            "Recognized text: %r (confidence=%.3f)",
                            stripped, result.confidence,
                        )
                        logger.info(
                            "Processing conversation: '%s' (speech confidence=%.3f)",
                            stripped, result.confidence,
                        )
                        self._run_command(
                            stripped,
                            speech_confidence=result.confidence,
                        )
                        # Requirement #9: a follow-up command keeps the conversation
                        # open — it only ends on timeout / sleep / goodbye / cancel /
                        # 30 s of true silence.
                        if self._conversation_manager.has_pending_confirmation:
                            self._conversation_manager.reset_activity()
                        else:
                            self._conversation_manager.transition_to_active(
                                "command complete"
                            )
                    else:
                        reason = result.reason or ""
                        text = (result.text or "").strip()

                        if reason == "no_speech":
                            # 30 s of true silence -> end the conversation (#9).
                            logger.info(
                                "Conversation ended — no speech for %.0fs", listen_to
                            )
                            self._conversation_manager.on_timeout()
                            bridge.set_core_state("idle")
                            bridge.show_subtitle(
                                "Conversation timed out. Say 'JARVIS' or type a command."
                            )
                            self._voice_engine.stop_barge_in()
                            continue

                        consecutive_failed_listens += 1
                        if (
                            consecutive_failed_listens
                            >= _MAX_CONSECUTIVE_FAILED_LISTENS
                        ):
                            logger.warning(
                                "No speech understood after %d attempts — ending conversation",
                                consecutive_failed_listens,
                            )
                            bridge.show_subtitle(
                                "I couldn't hear you. Let's pick this up later — say 'JARVIS' when ready."
                            )
                            self._speak_with_retry(
                                "I couldn't hear you. Let's pick this up later. Say JARVIS when ready."
                            )
                            self._wait_for_speech_end(timeout=10.0)
                            self._conversation_manager.on_timeout()
                            bridge.set_core_state("idle")
                            continue

                        # The user spoke but was not understood — this is activity,
                        # so restart the silence window and ask them to repeat.
                        self._conversation_manager.reset_activity()
                        if reason == "low confidence":
                            logger.info(
                                "Conversation low confidence (%.3f) — asking to repeat",
                                result.confidence,
                            )
                            bridge.show_subtitle(
                                "Sorry sir, could you repeat that?"
                            )
                            self._speak_with_retry(
                                "Sorry sir, could you repeat that?"
                            )
                            self._wait_for_speech_end(timeout=10.0)
                            continue
                        logger.info(
                            "Conversation rejected (%s) — asking to repeat", reason
                        )
                        bridge.show_subtitle(
                            "I didn't catch that. Please try again."
                        )
                        self._speak_with_retry(
                            "I didn't catch that. Please try again."
                        )
                        self._wait_for_speech_end(timeout=10.0)

                time.sleep(_BACKEND_LOOP_SLEEP)

        except Exception as exc:
            logger.error("Conversation owner error: %s", exc, exc_info=True)
            try:
                bridge.set_core_state("error")
                bridge.show_subtitle("An error occurred — check the logs.")
            except Exception:
                pass
        finally:
            logger.info("Conversation owner loop shutting down")
            try:
                bridge.set_core_state("offline")
            except Exception:
                pass
            svc_results = self._service_manager.shutdown_all()
            failures = {n: o for n, o in svc_results.items() if o != "ok"}
            if failures:
                logger.warning("Service shutdown issues: %s", failures)
            self._microphone_stream.shutdown()
            logger.info("Conversation owner shut down")
            try:
                self._shutdown_event.set()
                from PySide6.QtCore import QMetaObject, Qt, QCoreApplication
                QMetaObject.invokeMethod(
                    QCoreApplication.instance(), "quit",
                    Qt.ConnectionType.QueuedConnection,
                )
            except Exception:
                pass

    # ------------------------------------------------------------------
    # Watchdog recovery
    # ------------------------------------------------------------------

    def _on_backend_stall(self, name: str) -> None:
        """Recovery attempt when the backend loop stalls: cancel the hung
        task (firing its cleanup) so the loop can resume, and surface
        Core Offline."""
        logger.critical(
            "Backend watchdog: '%s' stalled — attempting recovery", name
        )
        try:
            self._task_manager.cancel_active(reason="backend stall")
        except Exception as exc:
            logger.error("Backend recovery: task cancel failed: %s", exc)
        try:
            self._brain.cancel_current()
        except Exception as exc:
            logger.error("Backend recovery: brain.cancel_current failed: %s", exc)
        try:
            self._bridge.set_core_state("offline")
            self._bridge.show_subtitle(
                "Core Offline — backend stalled. Attempting to recover..."
            )
        except Exception:
            pass

    def _on_conversation_stall(self, name: str) -> None:
        """Recovery when a conversation stalls (e.g. stuck listening):
        force the conversation back to Idle so the UI can never remain in
        LISTENING indefinitely."""
        logger.critical(
            "Conversation watchdog: '%s' stalled — forcing idle", name
        )
        try:
            self._conversation_manager.on_timeout()
        except Exception as exc:
            logger.error("Conversation recovery: on_timeout failed: %s", exc)
        try:
            self._duplex_session.cancel_capture()
        except Exception as exc:
            logger.error("Conversation recovery: cancel_capture failed: %s", exc)
        try:
            self._microphone_stream.unmute()
        except Exception:
            pass
        try:
            self._bridge.set_core_state("idle")
            self._bridge.show_subtitle(
                "Conversation recovered. Say 'JARVIS' or type a command."
            )
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Command lifecycle
    # ------------------------------------------------------------------

    def _run_command(
        self,
        command: str,
        speech_confidence: float | None = None,
        speech_recognition_ms: float | None = None,
    ):
        """Run one command as a managed task.

        Accepting the command cancels any previous task (firing its cleanup),
        runs ``brain.process`` with the task's cancel event, presents the
        response, waits for speech, finalizes the task, and always returns the
        backend to Idle — even on timeout, exception, or cancellation.
        """
        task_started = time.monotonic()
        task = self._task_manager.create_task(command)
        self._brain.cancel_current()
        self._register_task_cleanup(task)
        self._bridge.set_core_state("thinking")
        self._bridge.set_current_task(command)
        response = None
        try:
            self._watchdog_manager.kick("backend_loop")
            response = self._brain.process(
                command,
                cancel_event=task.cancel_event,
                speech_confidence=speech_confidence,
            )
        except Exception as exc:
            logger.error("Brain process failed: %s", exc, exc_info=True)
            response = None
        finally:
            self._bridge.set_current_task("")
            brain_ms = (time.monotonic() - task_started) * 1000.0
            if speech_recognition_ms is not None:
                logger.info(
                    "LATENCY stage=recognition->intent+execution %.0f ms "
                    "(recognition=%.0f ms, total=%d ms, command=%r)",
                    brain_ms, speech_recognition_ms,
                    int((time.monotonic() - task_started) * 1000.0),
                    command,
                )

        if response is not None:
            self._present_response(response)
            if getattr(response, "needs_clarification", False):
                self._store_pending_from_response(response, command)

        # Cap the wait so a TTS failure never freezes the loop.
        self._wait_for_speech_end(timeout=30.0)
        self._finalize_task(task, response)
        self._bridge.set_core_state("idle")

        total_ms = (time.monotonic() - task_started) * 1000.0
        data = getattr(response, "data", {}) or {}
        logger.info(
            "COMMAND COMPLETE: command=%r speech_confidence=%s "
            "success=%s status=%s task_result=%s intent=%s "
            "total_time=%.1f ms",
            command,
            f"{speech_confidence:.3f}" if speech_confidence is not None else "-",
            bool(response and getattr(response, "success", False)),
            response.task_result.value if response is not None else "NONE",
            getattr(response, "task_result", None),
            (data.get("intent") or getattr(response, "data", {}).get("intent") or "-"),
            total_ms,
        )
        return response

    def _present_response(self, response) -> None:
        bridge = self._bridge
        subtitle = self._response_manager.console_text(response)
        bridge.show_subtitle(subtitle)
        if self._response_manager._voice_enabled:
            message = self._response_manager.voice_text(response)
            if message:
                # Replace any name-based greetings with neutral forms
                message = self._sanitize_voice_response(message)
                if message:
                    # Never let stale/queued speech overlap a new response —
                    # stop and clear anything still playing before enqueueing.
                    try:
                        self._voice_engine.cancel_all()
                    except Exception as exc:
                        logger.error("VoiceEngine cancel_all failed: %s", exc)
                    bridge.set_core_state("speaking")
                    self._speak_with_retry(message)
        if not getattr(response, "success", True):
            task_result = getattr(response, "task_result", None)
            logger.info(
                "Task result: %s | message: %s",
                task_result, getattr(response, "message", ""),
            )

    def _check_pending_confirmation(self, text: str) -> bool:
        """Check if there's a pending confirmation and route to brain.resolve_context().

        Returns True if the text was a confirmation reply (consumed), False otherwise.
        """
        if not self._conversation_manager.has_pending_confirmation:
            return False

        logger.info(
            "Routing '%s' to resolve_context (pending confirmation exists)", text
        )
        self._bridge.set_core_state("thinking")
        try:
            response = self._brain.resolve_context(text)
        except Exception as exc:
            logger.error("brain.resolve_context failed: %s", exc, exc_info=True)
            response = None

        if response is not None:
            self._present_response(response)
            self._wait_for_speech_end(timeout=30.0)
            if not getattr(response, "needs_clarification", False):
                # Resolved — stay engaged for follow-ups (#9)
                self._conversation_manager.transition_to_active(
                    "confirmation resolved"
                )
            # If still needs clarification (unclear answer), keep pending
            else:
                self._conversation_manager.reset_activity()
        else:
            self._conversation_manager.return_to_idle("resolve_context error")

        return True

    def _store_pending_from_response(self, response, raw_text: str) -> None:
        """If the response needs clarification/confirmation,
        store the pending info in the conversation manager."""
        if not getattr(response, "needs_clarification", False):
            return
        data = getattr(response, "data", {}) or {}
        intent = data.get("intent", "")
        if intent:
            logger.debug("Confirmation stored — intent=%s raw=%s", intent, raw_text)
            entities = {}
            self._conversation_manager.request_confirmation(intent, entities, raw_text)
        else:
            logger.debug("Clarification pending — raw=%s", raw_text)
            self._conversation_manager.request_confirmation(
                "clarification", {}, raw_text
            )

    def _register_task_cleanup(self, task) -> None:
        """Attach the cleanup callbacks that run when *task* is cancelled/fails.

        Covers browser automation, TTS, listeners, timers and the mic so a
        superseded task can never leave the system mid-action.
        """
        callbacks = [
            self._brain.cancel_current,
            self._voice_engine.cancel_all,
            self._voice_engine.stop_barge_in,
            self._wake_word_service.reset_for_wake,
            self._microphone_stream.unmute,
        ]
        duplex_session = getattr(self._voice_engine, "_duplex_session", None)
        if duplex_session is not None:
            callbacks.append(duplex_session.cancel_capture)
        for callback in callbacks:
            self._task_manager.register_cleanup(task, callback)

    def _finalize_task(self, task, response) -> None:
        """Mark the task SUCCESS/FAILED once its command has been answered."""
        if response is None:
            self._task_manager.mark_failed(task, reason="no_response")
            return
        result = getattr(response, "task_result", None)
        value = result.value if result is not None else ""
        if value in (
            "SUCCESS", "CLARIFICATION", "USER_CONFIRMATION", "UNSUPPORTED",
            "CANCELLED",
        ):
            self._task_manager.mark_success(task)
        else:
            self._task_manager.mark_failed(task, reason=value.lower() or "failed")

    # ------------------------------------------------------------------
    # Speech helpers
    # ------------------------------------------------------------------

    def _speak_with_retry(self, message: str) -> bool:
        """Speak *message* with one retry; never silently drops the utterance."""
        for attempt in (1, 2):
            try:
                self._voice_engine.speak(message)
                return True
            except Exception as exc:
                logger.error(
                    "TTS speak failed (attempt %d of 2): %s", attempt, exc
                )
                try:
                    self._voice_engine.interrupt()
                except Exception:
                    pass
                if attempt == 1:
                    time.sleep(0.3)
        logger.error("TTS failed after retries — message not spoken: %r", message)
        return False

    def _wait_for_speech_end(self, timeout: float = 30.0) -> None:
        """Block until TTS finishes or timeout expires.

        Uses the engine's busy state (queued + generating + playing) so the wait
        never exits early while audio is still being generated.  Also keeps the
        backend watchdog alive during a long-but-legitimate playback so it is
        never misreported as a stall.
        """
        deadline = time.monotonic() + timeout
        # Give the provider a moment to start playing (async providers have a
        # short startup window before is_playing becomes True).
        time.sleep(0.05)
        last_kick = 0.0
        while time.monotonic() < deadline:
            busy = getattr(self._voice_engine, "is_busy", None)
            if busy is None:
                busy = (
                    bool(self._voice_engine.is_speaking)
                    or self._voice_engine.queue_size > 0
                )
            if not busy:
                break
            now = time.monotonic()
            if now - last_kick >= 1.0:
                last_kick = now
                try:
                    self._watchdog_manager.kick("backend_loop")
                    self._watchdog_manager.kick("conversation")
                except Exception:
                    pass
            time.sleep(0.02)
        else:
            logger.warning(
                "_wait_for_speech_end: timed out after %.0fs — forcing idle",
                timeout,
            )

    @staticmethod
    def _strip_wake_word(text: str) -> str | None:
        stripped = _WAKE_PATTERN.sub("", text)
        stripped = re.sub(r"\s+", " ", stripped).strip()
        if not stripped:
            return None
        return stripped

    @staticmethod
    def _sanitize_voice_response(text: str) -> str:
        """Replace name-based greetings with neutral forms."""
        # Replace "Yes Hashim", "Yes, Hashim", "Yes sir Hashim" etc.
        text = re.sub(
            r'\bYes[,\s]+(?:sir\s+)?(?:Hashim|Muhammad|Muhammed|Hassan|Ahmed|Ali)\b',
            'Yes, sir.',
            text, flags=re.IGNORECASE,
        )
        return text.strip()