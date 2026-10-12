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
import sys
import threading
import time
import traceback
from typing import Any

from brain.intent_normalizer import Intent, normalize as normalize_intent
from monitoring.instrumentation import Timer
from monitoring.pipeline_trace import (
    set_trace_state as _set_trace_state,
    stage_entry as _stage_entry,
    stage_exit as _stage_exit,
)
from monitoring.turn_trace import mark as turn_mark
from services.conversation_manager import ConversationManager, ConversationState
from services.silence_gate import is_silence_or_garbage
from thinking.speech_intelligence import (
    SpeechAction,
    SpeechIntelligenceLayer,
    SpeechTranscript,
)
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
_MAX_WAKE_NO_SPEECH_ROUNDS = 3
_MAX_WAKE_REPEAT_ROUNDS = 3
# PART 3: the wake-to-command listen window waits for *speech start* for a
# SHORT time and then returns to wake/idle — it never sits silent for the
# full 30 s.  (The speech-end wait is owned by the capture VAD, not here.)
_WAKE_LISTEN_TIMEOUT_SECONDS = 10.0
# While a capture is in flight the conversation loop is blocked inside
# ``capture_command`` and cannot kick the liveness watchdogs itself.  A single
# utterance can legitimately occupy that thread for a minute or more (a 15 s
# max utterance followed by several full transcription passes), so an
# in-flight capture must be reported as progress rather than a stall.
_CAPTURE_HEARTBEAT_SECONDS = 1.0

_WAKE_PHRASE = "monday"
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
        speech_intelligence: SpeechIntelligenceLayer | None = None,
        wake_word_enabled: bool | None = None,
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
        self._speech_intelligence = speech_intelligence or SpeechIntelligenceLayer()
        # VOICE-PIPELINE-004: single source of truth for direct-listening mode.
        # Defaults to the WAKE_WORD_ENABLED setting; tests may inject explicitly.
        if wake_word_enabled is None:
            from config.settings import WAKE_WORD_ENABLED

            wake_word_enabled = WAKE_WORD_ENABLED
        self._wake_word_enabled = bool(wake_word_enabled)
        # Microphone recovery: next allowed restart attempt (monotonic).
        self._mic_retry_at = 0.0
        # Whether the mic-unavailable error is currently published (so the
        # recovery loop publishes it once instead of spamming history).
        self._mic_error_published = False
        # State-change watchdog: track last conversation state change.
        self._last_state_change = time.monotonic()
        self._state_watchdog_timeout = 20.0

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
        bridge.emit_passive("System ready")
        # Never claim LLM reasoning when the provider is down.  Health is
        # probed once here (lazy, cached); per-call fail-fast in the
        # provider keeps later commands fast — no health check per request.
        try:
            _reasoner = getattr(self._brain, "reasoner", None)
            if _reasoner is None:
                _reasoner = getattr(self._brain, "_reasoner", None)
            _llm = getattr(_reasoner, "_llm", None) if _reasoner is not None else None
            if _llm is not None and hasattr(_llm, "provider_name"):
                _provider_name = _llm.provider_name
                _llm_ok = _llm.health_check()
            else:
                # Brain does not expose its reasoner: probe once via a
                # throwaway dispatcher (startup only — never per request).
                from brain.llm import LLM as _LLM

                _probe = _LLM()
                _provider_name = _probe.provider_name
                _llm_ok = _probe.health_check()
        except Exception:
            _provider_name = "rules"
            _llm_ok = False
        if not _llm_ok:
            logger.warning(
                "LLM reasoning OFF at startup (provider=%s) — "
                "rule pipeline active", _provider_name,
            )

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
        # State-change watchdog: if conversation state doesn't change for 20s
        # outside LISTENING, dump thread stacks and recover to listening.
        self._watchdog_manager.add(
            "state_change",
            timeout=self._state_watchdog_timeout,
            on_stall=self._on_state_change_stall,
        )

        logger.info("Conversation owner ready")
        consecutive_failed_listens = 0
        conversation_repeat_rounds = 0
        _last_known_state = self._conversation_manager.state

        try:
            while True:
                if self._shutdown_in_progress.is_set():
                    logger.info("Conversation owner shutdown requested — exiting loop")
                    break
                try:
                    self._watchdog_manager.kick("backend_loop")
                    self._watchdog_manager.kick("conversation")
                    
                    # Track conversation state changes for the state-change watchdog
                    current_state = self._conversation_manager.state
                    if current_state != _last_known_state:
                        _last_known_state = current_state
                        self._last_state_change = time.monotonic()
                        self._watchdog_manager.kick("state_change")

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
                            bridge.show_subtitle("Ending conversation.")
                            self._conversation_manager.return_to_idle("exit command")
                            bridge.emit_passive("Conversation ended")
                            continue

                        # ── Check pending confirmation BEFORE processing ──
                        if self._check_pending_confirmation(command):
                            continue

                        logger.info("Processing text: '%s'", command)
                        logger.info("Recognized text: %r", command)
                        self._run_command_safe(command)
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
                    # Voice (direct listening / wake-gated)
                    # ============================================================
                    if self._conversation_manager.state in (ConversationState.IDLE,):
                        # VOICE-PIPELINE-004: when WAKE_WORD_ENABLED=false the owner
                        # must NOT wait for WakeWordService — it enters the
                        # capture/listen path immediately, and the state machine
                        # records what actually happens (LISTENING), never a
                        # fabricated WAKE_DETECTED / "wake word heard" transition.
                        wake_event = self._wake_word_detected.is_set()
                        enter_listen = (not self._wake_word_enabled) or wake_event
                        if enter_listen:
                            wake_start = _stage_entry("backend.wake_command")
                            self._brain.cancel_current()
                            if wake_event:
                                # A real wake word was heard — represent it honestly.
                                self._wake_word_detected.clear()
                                self._conversation_manager.on_wake_word()
                                wake_active = True
                            else:
                                # Direct listening — no wake word involved at all.
                                self._conversation_manager.on_listening()
                                wake_active = False
                            # Gate entry too: never publish LISTENING (or run
                            # a capture below) while the mic path is dead. A
                            # dead mic reports honest error + restart
                            # attempt; the outer loop re-gates next pass.
                            if not self._ensure_listening_ready():
                                self._handle_listening_not_ready(bridge)
                                _stage_exit(
                                    "backend.wake_command", wake_start,
                                    status="MIC_NOT_READY",
                                )
                                time.sleep(0.5)
                                continue
                            bridge.emit_listening("Listening...")
                            logger.info("TURN LISTENING READY (direct/wake entry)")

                            self._watchdog_manager.kick("backend_loop")
                            self._watchdog_manager.kick("conversation")
                            # Confirm aloud ("Yes?") WITHOUT muting the mic: the echo
                            # canceller removes JARVIS's own voice from the capture, so
                            # the user can start speaking the moment they hear it — the
                            # first word is recovered from the pre-roll buffer.
                            # FIX-VOICE-001: no spoken ack after the wake word.  An
                            # audible "Yes?" re-triggers JARVIS's own mic and burns
                            # the first words of the user's command, so the ack is
                            # silenced (subtitle only).
                            # PART 8: the wake ack must never delay mic capture.  The
                            # capture starts immediately below — any word spoken right
                            # after "Yes?" is recovered from the pre-roll, and the echo
                            # canceller prevents JARVIS hearing its own "Yes?".

                            # ── Listen-to-command loop (direct or wake-gated) ──
                            handled = False
                            no_speech_rounds = 0
                            repeat_rounds = 0
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
                                # LISTENING is published only after the mic
                                # path is verified really ready (consumer
                                # attached, capture thread alive, unmuted) —
                                # the backend owns state, the UI only reflects
                                # it.  A dead mic skips capture this pass
                                # (honest error + restart attempt) instead of
                                # faking "listening" while deaf.
                                if not self._ensure_listening_ready():
                                    self._handle_listening_not_ready(bridge)
                                    time.sleep(0.5)
                                    continue
                                bridge.emit_listening("Listening...")
                                logger.debug("TURN LISTENING READY (capture pass)")
                                try:
                                    with Timer("capture_command"):
                                        result = self._capture_with_heartbeat(
                                            timeout=_WAKE_LISTEN_TIMEOUT_SECONDS,
                                            on_partial=lambda text: bridge.show_subtitle(text),
                                        )
                                except Exception as exc:
                                    logger.error(
                                        "Voice capture failed: %s", exc, exc_info=True
                                    )
                                    result = CaptureResult(
                                        "", 0.0, False, reason="capture_error"
                                    )
                                # Safety: never leave the mic muted after capture.
                                self._microphone_stream.unmute()
                                # A completed capture is pipeline progress.
                                self._note_activity()
                                logger.debug("TURN MIC REARMED (post-capture)")

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
                                        bridge.emit_passive("Conversation ended")
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

                                    turn_mark(
                                        "UTTERANCE_ACCEPTED",
                                        gen=getattr(self._duplex_session, "capture_generation", None),
                                        text_len=len(stripped),
                                        confidence=round(float(result.confidence), 3),
                                    )
                                    turn_mark(
                                        "CONVERSATION_EVENT_QUEUED",
                                        gen=getattr(self._duplex_session, "capture_generation", None),
                                    )
                                    logger.info(
                                        "Recognized text: %r (confidence=%.3f)",
                                        stripped, result.confidence,
                                    )
                                    logger.info(
                                        "Processing voice: '%s' (speech confidence=%.3f)",
                                        stripped, result.confidence,
                                    )
                                    self._run_command_safe(
                                        stripped,
                                        speech_confidence=result.confidence,
                                        speech_recognition_ms=result.recognition_ms,
                                        word_confidences=result.word_confidences,
                                        min_word_confidence=result.min_word_confidence,
                                        speech_seconds=result.speech_seconds,
                                    )
                                    # Requirement #9: stay engaged for follow-ups instead
                                    # of dropping straight back to wake mode.
                                    if self._conversation_manager.has_pending_confirmation:
                                        self._conversation_manager.reset_activity()
                                    else:
                                        self._conversation_manager.transition_to_active(
                                            "command complete"
                                        )
                                    conversation_repeat_rounds = 0
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
                                        _WAKE_LISTEN_TIMEOUT_SECONDS, no_speech_rounds,
                                    )
                                    if no_speech_rounds >= _MAX_WAKE_NO_SPEECH_ROUNDS:
                                        # FIX-NO-WAKE-ECHO: end silently with a
                                        # short neutral note.  Speaking "Say JARVIS"
                                        # aloud plays the wake phrase through the
                                        # speakers — residual echo re-triggers the
                                        # wake detector the moment it is re-armed,
                                        # and the 10 s TTS wait delays conversation
                                        # end without value.
                                        bridge.show_subtitle("Ready when you are.")
                                        if not self._wake_word_enabled:
                                            no_speech_rounds = 0
                                            continue
                                        self._conversation_manager.return_to_idle(
                                            "no speech"
                                        )
                                        # DIRECT-LISTEN-STABLE: with the wake word
                                        # disabled the UI holds one stable
                                        # listening/ready state — never bouncing
                                        # idle <-> listening between captures.
                                        if self._wake_word_enabled:
                                            bridge.emit_passive("No speech — ready")
                                        _stage_exit(
                                            "backend.wake_command",
                                            wake_start,
                                            status="NO_SPEECH",
                                        )
                                        handled = True
                                        break
                                    # Requirement #3: stay listening — never exit just
                                    # because the timer ran out.  VOICE-PIPELINE-004:
                                    # silent background — never speak "I'm still
                                    # listening."; subtitle only, keep listening.
                                    bridge.show_subtitle("I'm still listening.")
                                    continue

                                # PART 13: silence / noise / empty / garbage never starts
                                # a repeat loop — it returns to wake/idle quietly.  A
                                # decoder run-away (pathological repetition), an empty
                                # recognition, a fragment, or a cancelled capture are not
                                # "I didn't understand you" situations.
                                if is_silence_or_garbage(text, reason):
                                    logger.info(
                                        "WAKE_CAPTURE %s (text=%r) — returning to idle",
                                        reason or "empty", text,
                                    )
                                    bridge.show_subtitle("Ready when you are.")
                                    if not self._wake_word_enabled:
                                        continue
                                    self._conversation_manager.return_to_idle(
                                        "no speech"
                                    )
# DIRECT-LISTEN-STABLE (see above).
                                    if self._wake_word_enabled:
                                        bridge.emit_passive("No speech — ready")
                                    handled = True
                                    break

                                if reason == "low confidence":
                                    # Requirement #6: never execute a low-confidence
                                    # command.  One concise repeat-ask, then we return
                                    # to idle — never an endless loop (PART 13).
                                    if not self._wake_word_enabled:
                                        # Direct listening keeps the microphone
                                        # open permanently, so low-confidence
                                        # fragments arrive from ordinary
                                        # background noise.  Speaking a repeat nag
                                        # (and blocking on the 10 s TTS wait)
                                        # would make JARVIS talk to itself —
                                        # subtitle only, exactly like the
                                        # no-speech branch above.
                                        logger.info(
                                            "WAKE_CAPTURE low confidence (%.3f) — "
                                            "direct listening, subtitle only",
                                            result.confidence,
                                        )
                                        bridge.show_subtitle("Ready when you are.")
                                        continue
                                    repeat_rounds += 1
                                    if repeat_rounds >= _MAX_WAKE_REPEAT_ROUNDS:
                                        logger.info(
                                            "WAKE_CAPTURE low confidence repeated %d "
                                            "rounds — returning to idle",
                                            repeat_rounds,
                                        )
                                        bridge.show_subtitle("Ready when you are.")
                                        if not self._wake_word_enabled:
                                            repeat_rounds = 0
                                            continue
                                        self._conversation_manager.return_to_idle(
                                            "repeat limit"
                                        )
                                        # DIRECT-LISTEN-STABLE (see above).
                                        if self._wake_word_enabled:
                                            bridge.emit_passive("Repeat limit — ready")
                                        handled = True
                                        break
                                    logger.info(
                                        "WAKE_CAPTURE low confidence (%.3f) - asking to repeat",
                                        result.confidence,
                                    )
                                    bridge.show_subtitle(
                                        "Sorry sir, could you repeat that?"
                                    )
                                    self._speak_with_retry("Sorry sir, could you repeat that?")
                                    self._wait_for_speech_end(timeout=10.0)
                                    continue

                                # Requirement #7: partial words / other rejections.
                                logger.info(
                                    "WAKE_CAPTURE rejected (%s) — returning to idle", reason
                                )
                                bridge.show_subtitle("Ready when you are.")
                                if not self._wake_word_enabled:
                                    continue
                                self._conversation_manager.return_to_idle(
                                    "rejected capture"
                                )
                                # DIRECT-LISTEN-STABLE (see above).
                                if self._wake_word_enabled:
                                    bridge.emit_passive("Rejected — ready")
                                handled = True
                                break

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
                        # FIX 2: single authoritative predicate.  is_speaking is
                        # False while an utterance is still being generated
                        # (dequeued, HTTP in flight), which used to start a
                        # fresh capture mid-generation; is_busy covers queued
                        # + generating + playing so listening never starts early.
                        _engine_busy = getattr(self._voice_engine, "is_busy", None)
                        if _engine_busy is None:
                            _engine_busy = (
                                bool(self._voice_engine.is_speaking)
                                or self._voice_engine.queue_size > 0
                            )
                        if _engine_busy:
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
                            bridge.emit_passive("Conversation timed out")
                            bridge.show_subtitle("Conversation timed out.")
                            self._voice_engine.stop_barge_in()
                            continue

                        # A fresh 30 s of true silence starts now that JARVIS has
                        # finished speaking (Requirement #9).
                        self._conversation_manager.reset_activity()
                        listen_to = min(
                            _CONVERSATION_AUTO_SLEEP_SECONDS,
                            max(1.0, self._conversation_manager.remaining_time),
                        )
                        # Record the true per-turn lifecycle (LISTENING ->
                        # THINKING -> SPEAKING -> LISTENING).  Confirmation
                        # state is preserved so its shorter expiry keeps
                        # applying while awaiting the reply.
                        if (
                            self._conversation_manager.state
                            == ConversationState.ACTIVE_CONVERSATION
                        ):
                            self._conversation_manager.on_listening()
                        # LISTENING is published only after the mic path is
                        # verified really ready (see IDLE branch above).
                        # A dead mic skips capture this pass (honest error
                        # + restart attempt) instead of faking "listening".
                        if not self._ensure_listening_ready():
                            self._handle_listening_not_ready(bridge)
                            time.sleep(0.5)
                            continue
                        bridge.emit_listening("Listening...")
                        logger.info("TURN LISTENING READY (conversation follow-up)")
                        active_start = _stage_entry("backend.conversation_listen")
                        try:
                            with Timer("capture_command"):
                                result = self._capture_with_heartbeat(
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
                        # A completed capture is pipeline progress.
                        self._note_activity()
                        logger.debug("TURN MIC REARMED (conversation post-capture)")
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
                                bridge.emit_passive("Conversation ended")
                                continue

                            stripped = self._strip_wake_word(text) or text

                            # ── Check pending confirmation BEFORE processing ──
                            if self._check_pending_confirmation(stripped):
                                self._conversation_manager.reset_activity()
                                continue

                            turn_mark(
                                "UTTERANCE_ACCEPTED",
                                gen=getattr(self._duplex_session, "capture_generation", None),
                                text_len=len(stripped),
                                confidence=round(float(result.confidence), 3),
                            )
                            turn_mark(
                                "CONVERSATION_EVENT_QUEUED",
                                gen=getattr(self._duplex_session, "capture_generation", None),
                            )
                            logger.info(
                                "Recognized text: %r (confidence=%.3f)",
                                stripped, result.confidence,
                            )
                            logger.info(
                                "Processing conversation: '%s' (speech confidence=%.3f)",
                                stripped, result.confidence,
                            )
                            self._run_command_safe(
                                stripped,
                                speech_confidence=result.confidence,
                                word_confidences=result.word_confidences,
                                min_word_confidence=result.min_word_confidence,
                                speech_seconds=result.speech_seconds,
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
                            conversation_repeat_rounds = 0
                        else:
                            reason = result.reason or ""
                            text = (result.text or "").strip()

                            if reason == "no_speech":
                                # 30 s of true silence -> end the conversation (#9).
                                logger.info(
                                    "Conversation ended — no speech for %.0fs", listen_to
                                )
                                self._conversation_manager.on_timeout()
                                bridge.emit_passive("Conversation timed out — no speech")
                                bridge.show_subtitle("Conversation timed out.")
                                self._voice_engine.stop_barge_in()
                                continue

                            # PART 13: silence / noise / empty / garbage is not "I
                            # didn't catch you" — it ends the conversation quietly
                            # (true silence), never a repeat loop.
                            if is_silence_or_garbage(text, reason):
                                logger.info(
                                    "Conversation ended — %s (text=%r)",
                                    reason or "empty", text,
                                )
                                self._conversation_manager.on_timeout()
                                bridge.emit_passive("Conversation timed out")
                                bridge.show_subtitle("Conversation timed out.")
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
                                    "I couldn't hear you. Let's pick this up later."
                                )
                                self._conversation_manager.on_timeout()
                                bridge.emit_passive("Could not understand")
                                continue

                            # The user spoke but was not understood — this is activity,
                            # so restart the silence window and ask them to repeat once.
                            self._conversation_manager.reset_activity()
                            if reason == "low confidence":
                                conversation_repeat_rounds += 1
                                if conversation_repeat_rounds >= _MAX_WAKE_REPEAT_ROUNDS:
                                    logger.info(
                                        "Conversation low confidence repeated %d "
                                        "rounds — returning to idle",
                                        conversation_repeat_rounds,
                                    )
                                    bridge.show_subtitle("Ready when you are.")
                                    self._conversation_manager.return_to_idle(
                                        "repeat limit"
                                    )
                                    conversation_repeat_rounds = 0
                                    continue
                                logger.info(
                                    "Conversation low confidence (%.3f) — asking to repeat",
                                    result.confidence,
                                )
                                bridge.show_subtitle(
                                    "Sorry sir, could you repeat that?"
                                )
                                spoken = self._speak_with_retry("Sorry sir, could you repeat that?")
                                if not spoken:
                                    logger.warning("TTS failed for repeat prompt; re-arming capture anyway")
                                self._wait_for_speech_end(timeout=10.0)
                                continue
                            logger.info(
                                "Conversation rejected (%s) — asking to repeat", reason
                            )
                            bridge.show_subtitle(
                                "I didn't catch that. Please try again."
                            )
                            spoken = self._speak_with_retry("I didn't catch that. Please try again.")
                            if not spoken:
                                logger.warning("TTS failed for repeat prompt; re-arming capture anyway")
                            self._wait_for_speech_end(timeout=10.0)

                    time.sleep(_BACKEND_LOOP_SLEEP)
                except Exception as exc:
                    # FIX-VOICE-RUNTIME-001: a recoverable runtime error
                    # must NEVER terminate JARVIS.  Log it, restore a usable
                    # state, and keep the persistent loop running.
                    logger.error("[RUNTIME] recoverable error: %s", exc, exc_info=True)
                    try:
                        self._microphone_stream.unmute()
                    except Exception:
                        pass
                    try:
                        self._conversation_manager.return_to_idle("runtime error")
                    except Exception:
                        pass
                    try:
                        bridge.emit_error("Something went wrong. I'm still here.", "Recoverable Error")
                    except Exception:
                        pass
                    logger.warning("[RUNTIME] returning to listening after recoverable error")
                    time.sleep(_BACKEND_LOOP_SLEEP)
                    continue

        except Exception as exc:
            logger.critical("[RUNTIME] conversation owner fatal error: %s", exc, exc_info=True)
            try:
                bridge.emit_error("An error occurred — check the logs.", "Fatal Error")
            except Exception:
                pass
        finally:
            # FIX-VOICE-003: disable automatic shutdown. Only legitimate
            # shutdown (user closing window, Ctrl+C) should terminate.
            # Recoverable errors return to idle mode instead of quitting.
            # The finally block now only handles cleanup, not shutdown.
            logger.info("[RUNTIME] conversation owner cleanup")
            try:
                bridge.emit_passive("Offline")
            except Exception:
                pass
            svc_results = self._service_manager.shutdown_all()
            failures = {n: o for n, o in svc_results.items() if o != "ok"}
            if failures:
                logger.warning("Service shutdown issues: %s", failures)
            self._microphone_stream.shutdown()
            logger.info("Conversation owner shut down")
            # FIX-VOICE-003: DO NOT call QCoreApplication.quit() here.
            # The application should only quit when explicitly requested
            # via the shutdown_in_progress event or text command.
            # Signal loop completion (cleanup is finished) — this is a
            # completion notification, not a quit request.
            try:
                self._shutdown_event.set()
            except Exception:
                pass

    # ------------------------------------------------------------------
    # Watchdog recovery
    # ------------------------------------------------------------------

    def _ensure_listening_ready(self) -> bool:
        """Verify the microphone path is really ready before LISTENING.

        LISTENING must mean: the capture thread runs, the duplex session
        still owns the mic consumer, the mic is not muted, and no stale
        capture state lingers.  Anything broken here is self-healed
        (consumer restored, mic unmuted, capture state reset) so a
        published "listening" UI state can never mask a dead mic.
        Returns True when the path is ready (healed or already healthy).
        """
        try:
            consumer_ok = self._microphone_stream.consumer_is(
                self._duplex_session.process_chunk
            )
        except Exception as exc:
            logger.error("Listening readiness: consumer check failed: %s", exc)
            consumer_ok = False
        if not consumer_ok:
            logger.warning(
                "Listening readiness: mic consumer not owned by duplex — "
                "restoring (was: %s)",
                type(getattr(
                    self._microphone_stream, "_consumer", None
                )).__name__,
            )
            try:
                self._microphone_stream.set_consumer(
                    self._duplex_session.process_chunk
                )
            except Exception as exc:
                logger.error("Listening readiness: consumer restore failed: %s", exc)
                return False
        try:
            running = bool(self._microphone_stream.is_running)
        except Exception:
            running = True
        if not running:
            logger.error("Listening readiness: capture thread not running")
            return False
        try:
            if self._microphone_stream.is_muted:
                logger.warning(
                    "Listening readiness: mic muted (owners=%s) — unmuting",
                    self._microphone_stream.mute_owners,
                )
                self._microphone_stream.unmute()
        except Exception as exc:
            logger.error("Listening readiness: unmute failed: %s", exc)
            return False
        self._mic_error_published = False
        return True

    def _handle_listening_not_ready(self, bridge) -> None:
        """Mic path not ready: never publish LISTENING.

        Publishes an honest ``error`` state (once, not spamming history)
        and periodically attempts a capture-thread restart, so a dead
        microphone is revived instead of running deaf forever behind a
        fake "listening" display.
        """
        try:
            running = bool(self._microphone_stream.is_running)
        except Exception:
            running = True
        if not running:
            now = time.monotonic()
            if now >= self._mic_retry_at:
                self._mic_retry_at = now + 5.0
                try:
                    self._microphone_stream.shutdown()
                except Exception as exc:
                    logger.error("Mic recovery shutdown failed: %s", exc)
                try:
                    self._microphone_stream.start()
                    logger.info("Mic recovery: capture thread restart attempted")
                except Exception as exc:
                    logger.error("Mic recovery restart failed: %s", exc)
        if not self._mic_error_published:
            self._mic_error_published = True
            try:
                bridge.emit_error("Microphone unavailable — retrying.", "Microphone Error")
            except Exception:
                pass

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
            # A capture wedged in finalize/decode also stalls the loop —
            # abort it (generation-tagged: a stale cancel can never kill
            # the next turn's capture once the loop resumes).
            self._duplex_session.cancel_capture()
        except Exception as exc:
            logger.error("Backend recovery: cancel_capture failed: %s", exc)
        try:
            self._bridge.emit_error("Core Offline — backend stalled. Attempting to recover...", "Backend Stalled")
        except Exception:
            pass

    def _on_conversation_stall(self, name: str) -> None:
        """Recovery when a conversation stalls (e.g. stuck listening):
        reset capture state and force the conversation back to Idle so
        the UI can never remain in LISTENING indefinitely.  The reset
        explicitly re-arms the listening path: with the wake word
        disabled the owner re-enters capture on its next loop pass;
        with the wake word enabled it waits for a genuine wake event."""
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
            reset = getattr(self._duplex_session, "reset_capture_state", None)
            if callable(reset):
                reset()
        except Exception as exc:
            logger.error("Conversation recovery: reset_capture_state failed: %s", exc)
        try:
            self._microphone_stream.unmute()
        except Exception:
            pass
        try:
            self._bridge.emit_passive("Conversation recovered")
            self._bridge.show_subtitle("Conversation recovered.")
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
        word_confidences: tuple[tuple[str, float], ...] = (),
        min_word_confidence: float | None = None,
        speech_seconds: float | None = None,
    ):
        """Run one command as a managed task.

        Accepting the command cancels any previous task (firing its cleanup),
        runs ``brain.process`` with the task's cancel event, presents the
        response, waits for speech, finalizes the task, and always returns the
        backend to Idle — even on timeout, exception, or cancellation.
        """
        # DIAGNOSTIC: Log STT result at pipeline entry
        logger.info(
            "PIPELINE_BOUNDARY: STT_RESULT text=%r confidence=%s "
            "speech_seconds=%s min_word_conf=%s",
            command,
            f"{speech_confidence:.3f}" if speech_confidence is not None else "N/A",
            f"{speech_seconds:.2f}" if speech_seconds is not None else "N/A",
            f"{min_word_confidence:.3f}" if min_word_confidence is not None else "N/A",
        )

        # FIX-002/FIX-003: gate voice transcripts through the Speech
        # Intelligence Layer so the planner never receives a raw STT
        # transcript.  Text commands (no speech confidence) pass through
        # unchanged.
        if speech_confidence is not None:
            command = self._apply_speech_intelligence(
                command, speech_confidence,
                word_confidences=word_confidences,
                min_word_confidence=min_word_confidence,
                speech_seconds=speech_seconds,
            )
            if command is None:
                return None

        # DIAGNOSTIC: Log Speech Intelligence result
        logger.info(
            "PIPELINE_BOUNDARY: SPEECH_INTELLIGENCE_RESULT text=%r",
            command,
        )

        task_started = time.monotonic()
        turn_mark(
            "CONVERSATION_EVENT_CONSUMED",
            gen=getattr(self._duplex_session, "capture_generation", None),
            text_len=len(command),
        )
        task = self._task_manager.create_task(command)
        self._task_manager.start_task(task)
        self._brain.cancel_current()
        self._register_task_cleanup(task)
        self._conversation_manager.on_command_received()
        self._bridge.emit_thinking(f"Processing: {command}")
        self._bridge.set_current_task(command)
        logger.info("TURN THINKING START command=%r", command)
        turn_mark(
            "THINKING_START",
            gen=getattr(self._duplex_session, "capture_generation", None),
        )
        response = None
        # Watchdog progress: brain.process() (online LLM) can legitimately
        # take tens of seconds.  Kick both watchdogs periodically while it
        # runs so a healthy long turn is never misreported as a stall.
        _brain_done = threading.Event()

        def _kick_while_thinking() -> None:
            while not _brain_done.wait(timeout=10.0):
                try:
                    self._watchdog_manager.kick("backend_loop")
                    self._watchdog_manager.kick("conversation")
                except Exception:
                    pass

        _kicker = threading.Thread(
            target=_kick_while_thinking, name="brain-progress-kick", daemon=True,
        )
        _kicker.start()
        try:
            self._watchdog_manager.kick("backend_loop")
            # DIAGNOSTIC: Log intent recognition entry
            logger.info("PIPELINE_BOUNDARY: INTENT_START text=%r", command)
            response = self._brain.process(
                command,
                cancel_event=task.cancel_event,
                speech_confidence=speech_confidence,
            )
        except Exception as exc:
            logger.error("Brain process failed: %s", exc, exc_info=True)
            response = None
        finally:
            _brain_done.set()
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
            # DIAGNOSTIC: Log intent/planning/execution result
            data = getattr(response, "data", {}) or {}
            intent = data.get("intent") or getattr(response, "data", {}).get("intent") or "unknown"
            task_result = response.task_result.value if response.task_result else "unknown"
            logger.info(
                "PIPELINE_BOUNDARY: INTENT_RESULT intent=%s task_result=%s success=%s",
                intent, task_result, getattr(response, "success", False),
            )
            logger.info("TURN RESPONSE READY command=%r", command)
            turn_mark(
                "RESPONSE_READY",
                gen=getattr(self._duplex_session, "capture_generation", None),
                success=bool(getattr(response, "success", False)),
            )
            self._present_response(response)
            if getattr(response, "needs_clarification", False):
                self._store_pending_from_response(response, command)

        # Cap the wait so a TTS failure never freezes the loop.
        self._wait_for_speech_end(timeout=30.0)
        logger.info("TURN TTS PLAYBACK END command=%r", command)
        try:
            self._microphone_stream.unmute()
        except Exception:
            pass
        logger.info("TURN MIC REARMED command=%r", command)
        turn_mark(
            "MIC_REARM",
            gen=getattr(self._duplex_session, "capture_generation", None),
        )
        self._finalize_task(task, response)
        # FIX 2: no unconditional idle here.  Every caller transitions the
        # manager next (usually to ACTIVE) and the loop publishes the
        # matching UI state (listening) — a forced idle would flash a false
        # IDLE in the middle of an engaged conversation and break the
        # THINKING → SPEAKING → LISTENING determinism.  Genuine ends
        # (exit/timeout/error) publish idle explicitly at their own sites.

        total_ms = (time.monotonic() - task_started) * 1000.0
        data = getattr(response, "data", {}) or {}
        
        # Per-turn latency breakdown
        stt_ms = speech_recognition_ms if speech_recognition_ms is not None else 0.0
        # TTS first-byte latency would need to be tracked from turn_trace marks
        # For now, log the key stages we have
        logger.info(
            "LATENCY SUMMARY turn=%s: total=%.0f ms stt=%.0f ms tts_first_byte=see_TTS_STREAM_START intent=%.0f ms exec=%.0f ms",
            getattr(self._duplex_session, "capture_generation", None),
            total_ms,
            stt_ms,
            brain_ms,  # intent+execution
            int((time.monotonic() - task_started) * 1000.0 - brain_ms),  # remainder
        )
        
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

    def _run_command_safe(self, *args, **kwargs):
        """PART 12: run a command without ever letting an unexpected failure
        escape to the outer loop (which would tear the whole owner down).  A
        command failure is recovered to Idle and the loop keeps running."""
        try:
            return self._run_command(*args, **kwargs)
        except Exception as exc:
            logger.error(
                "Command execution failed — recovering to idle: %s",
                exc, exc_info=True,
            )
            try:
                self._microphone_stream.unmute()
            except Exception:
                pass
            try:
                self._conversation_manager.return_to_idle("command error")
            except Exception:
                pass
            try:
                self._bridge.emit_error("Something went wrong with that command. Please try again.", "Command Error")
            except Exception:
                pass
            return None

    def _apply_speech_intelligence(
        self,
        command: str,
        speech_confidence: float,
        word_confidences: tuple[tuple[str, float], ...] = (),
        min_word_confidence: float | None = None,
        speech_seconds: float | None = None,
    ) -> str | None:
        """Run one voice transcript through the Speech Intelligence Layer.

        Returns the corrected command text for the planner, or ``None`` when
        the utterance was refused / a disambiguation question was asked (in
        which case JARVIS has already responded and nothing must execute).
        """
        decision = self._speech_intelligence.process(
            SpeechTranscript(
                text=command,
                confidence=speech_confidence,
                word_confidences=word_confidences,
                min_word_confidence=min_word_confidence,
                speech_seconds=speech_seconds,
            )
        )
        if decision.action in (SpeechAction.REFUSE, SpeechAction.ASK):
            message = self._sanitize_voice_response(decision.text)
            self._bridge.show_subtitle(decision.text)
            # FIX 2: refusal/ASK speech is real TTS — publish SPEAKING like
            # every other response so THINKING → SPEAKING → LISTENING stays
            # deterministic instead of speaking under a stale LISTENING.
            self._bridge.emit_speaking("Speaking...")
            self._conversation_manager.on_speaking()
            self._speak_with_retry(message)
            self._wait_for_speech_end(timeout=10.0)
            return None
        if decision.action is SpeechAction.CORRECT:
            logger.info(
                "Speech Intelligence: corrected %r -> %r (%s)",
                command, decision.text, decision.reason,
            )
        return decision.text

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
                    # Speech lifecycle is now managed by task cancellation.
                    # cancel_all() is called by task cleanup when a new command
                    # supersedes the current one. We don't call it here as a
                    # generic "prepare to speak" — that would race with the
                    # new speech generation. The VoiceManager's generation-safe
                    # cancel_all ensures only stale speech is cleared.
                    bridge.emit_speaking("Speaking...")
                    self._conversation_manager.on_speaking()
                    logger.info("TURN TTS START chars=%d", len(message))
                    turn_mark(
                        "TTS_REQUEST_START",
                        gen=getattr(self._duplex_session, "capture_generation", None),
                        chars=len(message),
                    )
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
        self._conversation_manager.on_command_received()
        self._bridge.emit_thinking("Processing follow-up...")
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
            # FIX 2: genuine conversation end — publish idle with the manager.
            self._bridge.emit_passive("Error resolving context")

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
            self._voice_engine.stop_barge_in,
            self._wake_word_service.reset_for_wake,
            self._microphone_stream.unmute,
        ]

        # TTS teardown is registered GUARDED.  ``Task._finalize`` runs cleanup
        # callbacks for every terminal state — including SUCCESS — and
        # ``cancel_all()`` stops playback *and* clears the queue.  On a normal
        # reply that raced the audio device: the log showed playback finishing
        # at 13.476 s and ``cancel_all()`` arriving at 13.542 s, while the
        # device still held buffered audio, so the last syllable of the
        # response was discarded.  A finished turn must not be cancelled; a
        # failed / superseded / timed-out turn must be.
        def _tts_cleanup() -> None:
            self._cancel_speech_unless_completed(task)

        callbacks.append(_tts_cleanup)
        duplex_session = getattr(self._voice_engine, "_duplex_session", None)
        if duplex_session is not None:
            callbacks.append(duplex_session.cancel_capture)
        for callback in callbacks:
            self._task_manager.register_cleanup(task, callback)

    def _cancel_speech_unless_completed(self, task) -> None:
        """Tear down TTS unless the task finished normally.

        Normal completion lets the player drain and close the stream on its
        own (see ``VoicePlayer._play_stream_worker``); cancelling there cut
        the tail off the reply and cleared unrelated queued speech.
        """
        status = getattr(task, "status", None)
        value = getattr(status, "value", status)
        cancel_event = getattr(task, "cancel_event", None)
        completed = value == "SUCCESS" and not (
            cancel_event is not None and cancel_event.is_set()
        )
        if completed:
            logger.debug(
                "TTS cancel skipped — task %s completed normally; playback "
                "drains naturally",
                getattr(task, "task_id", "?"),
            )
            return
        self._voice_engine.cancel_all()

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

    def _capture_with_heartbeat(
        self,
        *,
        timeout: float,
        on_partial: Any,
    ) -> CaptureResult:
        """Run one capture while keeping the liveness watchdogs fed.

        ``capture_command`` blocks this thread for its whole listen + VAD +
        transcription-retry budget, during which the loop cannot kick the
        ``backend_loop`` / ``state_change`` watchdogs itself — so a healthy
        utterance that took a while to transcribe used to publish
        ``ERROR [Backend Stalled] | Core Offline`` to the user.  The capture is
        bounded by its own hard limits (max utterance, finalize deadline), so
        an in-flight capture is progress: a small heartbeat thread reports it
        as such, while a loop wedged anywhere else still trips the watchdog.
        """
        stop = threading.Event()

        def _beat() -> None:
            while not stop.wait(_CAPTURE_HEARTBEAT_SECONDS):
                self._note_activity()
                try:
                    self._watchdog_manager.kick("backend_loop")
                    self._watchdog_manager.kick("conversation")
                except Exception:
                    pass

        heartbeat = threading.Thread(
            target=_beat, name="capture-heartbeat", daemon=True,
        )
        heartbeat.start()
        try:
            return self._duplex_session.capture_command(
                timeout=timeout, on_partial=on_partial,
            )
        finally:
            stop.set()
            self._note_activity()

    def _note_activity(self) -> None:
        """Record pipeline progress for the state-change watchdog.

        Direct listening cycles captures inside its own ``while not handled``
        loop, so the outer loop's state-change check — the thing that normally
        refreshes ``_last_state_change`` — is never reached while listening
        continues.  A completed capture is progress and must reset the clock,
        otherwise the watchdog fires in the instant between one capture
        ending and the next beginning.
        """
        self._last_state_change = time.monotonic()
        try:
            self._watchdog_manager.kick("state_change")
        except Exception:
            pass

    def _capture_is_active(self) -> bool:
        """True while the duplex session has a capture turn armed.

        The duplex session exposes this so the owner can distinguish a real
        LISTENING (capture armed) from a state that was merely published.
        """
        duplex = self._duplex_session
        checker = getattr(duplex, "is_capture_active", None)
        if not callable(checker):
            return False
        try:
            return bool(checker())
        except Exception:
            return False

    def _on_state_change_stall(self, name: str) -> None:
        """Watchdog callback: conversation state hasn't changed for the per-state limit.

        Dumps thread stacks (with thread names) and recovers based on state:
        - SPEAKING > 30s: interrupt TTS, return to listening
        - THINKING/WORKING > 60s: cancel task, return to listening
        - LISTENING with no active capture > 20s: restart capture
        - WAITING_CONFIRMATION: exempt (waits for user)
        - Other states > 20s: return to idle
        """
        current_state = self._conversation_manager.state
        elapsed = time.monotonic() - self._last_state_change

        # Per-state timeout limits
        if current_state == ConversationState.WAITING_CONFIRMATION:
            logger.debug(
                "State-change watchdog: WAITING_CONFIRMATION exempt from timeout "
                "(elapsed=%.1fs)", elapsed
            )
            self._watchdog_manager.kick("state_change")
            return

        if current_state == ConversationState.SPEAKING:
            limit = 30.0
        elif current_state in (ConversationState.THINKING, ConversationState.EXECUTING):
            limit = 60.0
        elif current_state == ConversationState.LISTENING:
            # VOICE-PIPELINE-004 keeps LISTENING deliberately stable ("one
            # stable listening/ready state — never bouncing idle <-> listening
            # between captures"), so a LISTENING state that is making progress
            # must not be treated as a stall.  An armed capture IS progress:
            # ``capture_command`` blocks for its idle timeout and then cycles.
            # Without this check the watchdog fired CRITICAL, dumped every
            # thread stack, and spuriously restarted the capture every ~20 s
            # during perfectly normal idle listening.
            if self._capture_is_active():
                self._last_state_change = time.monotonic()
                self._watchdog_manager.kick("state_change")
                return
            limit = 20.0
        else:
            limit = self._state_watchdog_timeout  # 20.0 default

        if elapsed < limit:
            # Not actually stalled yet - re-arm and return
            self._watchdog_manager.kick("state_change")
            return

        logger.critical(
            "State-change watchdog: conversation stuck in %s for %.1fs (limit=%.1fs) — "
            "dumping thread stacks and recovering",
            current_state.value if hasattr(current_state, 'value') else str(current_state),
            elapsed, limit,
        )

        # Dump thread stacks with thread names
        try:
            frames = sys._current_frames()
            lines = ["THREAD STACKS:"]
            for thread_id, frame in frames.items():
                # Find thread name
                thread_name = "unknown"
                for t in threading.enumerate():
                    if t.ident == thread_id:
                        thread_name = t.name
                        break
                lines.append(f"\n--- Thread {thread_id} ({thread_name}) ---")
                lines.extend(traceback.format_stack(frame))
            stack_dump = "\n".join(lines)
            logger.critical("%s", stack_dump)
        except Exception as exc:
            logger.error("Failed to dump thread stacks: %s", exc)

        # State-specific recovery
        recovery_ok = False
        if current_state == ConversationState.SPEAKING:
            # Interrupt TTS and return to listening
            try:
                self._voice_engine.interrupt(reason="state-watchdog speaking timeout")
                self._voice_engine.stop_barge_in()
                recovery_ok = True
                logger.info("Recovery: interrupted TTS in SPEAKING state")
            except Exception as exc:
                logger.warning("Recovery: failed to interrupt TTS: %s", exc)

        elif current_state in (ConversationState.THINKING, ConversationState.EXECUTING):
            # Cancel active task and return to listening
            try:
                self._task_manager.cancel_active(reason="state-watchdog thinking timeout")
                self._brain.cancel_current()
                self._duplex_session.cancel_capture()
                recovery_ok = True
                logger.info("Recovery: cancelled task in %s state", current_state)
            except Exception as exc:
                logger.warning("Recovery: failed to cancel task: %s", exc)

        elif current_state == ConversationState.LISTENING:
            # Check if there's an active capture; if not, restart capture
            try:
                capture_active = self._duplex_session.is_capture_active
            except Exception as exc:
                logger.error("Recovery: failed to check capture state: %s", exc)
                capture_active = False

            if capture_active:
                # Capture is running but stuck - cancel and let loop restart
                try:
                    self._duplex_session.cancel_capture()
                    logger.info("Recovery: cancelled stuck capture in LISTENING state")
                except Exception as exc:
                    logger.warning("Recovery: failed to cancel stuck capture: %s", exc)
            else:
                # No active capture - ensure listening path is ready and re-arm
                logger.info("Recovery: LISTENING with no active capture, re-arming capture path")
                try:
                    ready = self._ensure_listening_ready()
                    if ready:
                        logger.info("Recovery: listening path ready, loop will restart capture")
                        recovery_ok = True
                    else:
                        logger.warning("Recovery: listening path not ready after _ensure_listening_ready")
                except Exception as exc:
                    logger.warning("Recovery: _ensure_listening_ready failed: %s", exc)

        else:
            # Other states (IDLE, etc.) - return to idle
            try:
                self._conversation_manager.return_to_idle("state-change watchdog recovery")
                self._bridge.emit_passive("Conversation recovered from stall")
                self._bridge.show_subtitle("Conversation recovered.")
                recovery_ok = True
                logger.info("Recovery: returned to idle from %s state", current_state)
            except Exception as exc:
                logger.warning("Recovery: return_to_idle failed: %s", exc)

        # Common cleanup
        try:
            reset = getattr(self._duplex_session, "reset_capture_state", None)
            if callable(reset):
                reset()
                logger.debug("Recovery: reset_capture_state called")
        except Exception as exc:
            logger.warning("Recovery: reset_capture_state failed: %s", exc)

        try:
            self._microphone_stream.unmute()
        except Exception as exc:
            logger.warning("Recovery: microphone_stream.unmute failed: %s", exc)

        # Re-arm the watchdog for the new state
        self._last_state_change = time.monotonic()
        self._watchdog_manager.kick("state_change")

        if not recovery_ok:
            logger.warning("Recovery: no recovery action succeeded for state %s", current_state)

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
