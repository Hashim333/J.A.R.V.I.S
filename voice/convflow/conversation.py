"""
voice/convflow/conversation.py

``ConversationManager`` — the orchestrator for the redesign's conversation
model.

Two operating modes:

    * **Sleep Mode** (default).  Very low CPU.  Only the WakeWordManager is
      active; STT/LLM/TTS/automation are not running.
    * **Conversation Mode**.  Entered on wake ("jarvis"), acknowledged aloud,
      and stays active across many commands.  Every successful command resets
      a 10 s inactivity timer.  Follow-ups are processed with a temporary
      context memory (last app/browser/tab/video/folder/document/search/
      command).  The mode returns to Sleep only on a sleep command or when
      the timer expires with nothing speaking/executing/loading.

Guarantees of the redesign:

    * The wake word is never required again mid-conversation.
    * No false sleep: the machine never sleeps while the user is speaking,
      TTS is speaking, a command is executing, or the browser/automation is
      still loading.
    * Interruption: if the user starts speaking while JARVIS is speaking,
      TTS stops immediately and the pipeline re-enters Listening.

The 9-state :class:`ConversationStateMachine` (see ``states.py``) enforces
the state flow and rejects every illegal/forbidden-concurrent transition.
This orchestrator is standalone and injectable, so it can be driven by the
existing ``run.py`` backend loop or a future thread-safe event loop without
touching the UI.
"""
from __future__ import annotations

import logging
import threading
import time
from typing import Any, Callable

from voice.convflow.states import (
    ConversationStateMachine,
    VoiceState,
)
from voice.convflow.request_log import RequestLogRecord

logger = logging.getLogger(__name__)

DEFAULT_CONVERSATION_TIMEOUT_SECONDS = 10.0
DEFAULT_ACKNOWLEDGEMENT = "Yes?"
DEFAULT_SLEEP_RESPONSE = "Going back to sleep."

#: Explicit phrases that end Conversation Mode and return to Sleep.
_SLEEP_PHRASES = {
    "sleep", "go to sleep", "that's all", "enough", "goodbye", "good night",
    "goodnight", "stop listening", "cancel conversation", "exit conversation",
    "bye", "goodbye", "go idle", "never mind", "stand by",
}

#: Temporary context keys kept during Conversation Mode and cleared on sleep.
_CONTEXT_KEYS = (
    "last_app", "last_browser", "last_tab", "last_video",
    "last_folder", "last_document", "last_search", "last_command",
)


def is_sleep_phrase(text: str) -> bool:
    """True when *text* is an explicit sleep command."""
    if not isinstance(text, str):
        return False
    cleaned = " ".join(text.strip().casefold().split())
    if not cleaned:
        return False
    if cleaned in _SLEEP_PHRASES:
        return True
    return cleaned in {"sleep now", "go to sleep now", "i'm done", "we're done"}


class ConversationManager:
    """Sleep / Conversation Mode orchestrator (see module docstring).

    Args:
        state_machine: The 9-state machine (default: auto-created).
        wake: A :class:`WakeWordManager`-like object with ``arm``, ``disarm``,
            ``feed``, ``reset`` and an ``on_wake`` hook (injected).
        audio: An :class:`AudioCapture`-like object with ``start``/``shutdown``
            and a ``feed_playback_reference`` hook (injected).
        activity: A :class:`VoiceActivityDetector`-like object with
            ``begin``/``process_audio`` and speech callbacks (injected).
        recognizer: A :class:`SpeechRecognizer`-like object (injected).
        llm: An :class:`LLMRouter`-like object with ``route(...)`` (injected).
        dispatcher: A :class:`CommandDispatcher`-like object with
            ``dispatch(text, confidence)`` (injected).
        tts: A :class:`TTSManager`-like object (injected).
        conversation_timeout: Inactivity (seconds) before returning to Sleep.
        acknowledge: Greeting spoken on wake.
        sleep_response: Message spoken before returning to Sleep.
    """

    def __init__(
        self,
        state_machine: ConversationStateMachine | None = None,
        wake: Any | None = None,
        audio: Any | None = None,
        activity: Any | None = None,
        recognizer: Any | None = None,
        llm: Any | None = None,
        dispatcher: Any | None = None,
        tts: Any | None = None,
        conversation_timeout: float = DEFAULT_CONVERSATION_TIMEOUT_SECONDS,
        acknowledge: str = DEFAULT_ACKNOWLEDGEMENT,
        sleep_response: str = DEFAULT_SLEEP_RESPONSE,
        on_state_change: Callable[[VoiceState, VoiceState, str], None] | None = None,
    ) -> None:
        self._sm = state_machine or ConversationStateMachine()
        if on_state_change is not None:
            self._sm._on_change = on_state_change  # noqa: SLF001 - inject callback
        self._wake = wake
        self._audio = audio
        self._activity = activity
        self._recognizer = recognizer
        self._llm = llm
        self._dispatcher = dispatcher
        self._tts = tts
        self._conversation_timeout = float(conversation_timeout)
        self._acknowledge = acknowledge
        self._sleep_response = sleep_response

        self._last_activity: float | None = None
        self._context: dict[str, str] = {}
        self._active = False
        self._barge_in_pending = False
        self._request: RequestLogRecord | None = None
        self._lock = threading.RLock()

        # Wire wake hook.
        if self._wake is not None and not hasattr(self._wake, "_pipeline_wired"):
            try:
                self._wake._pipeline_wired = True  # noqa: SLF001 - injection guard
                self._wake._on_wake = self._on_wake  # noqa: SLF001
                self._wake._on_wake_latency = self._record_wake_latency  # noqa: SLF001
            except AttributeError:
                pass

        # Record structured LLM / execution timings from the worker.
        if self._dispatcher is not None and hasattr(self._dispatcher, "_on_stage"):
            self._dispatcher._on_stage = self._record_stage  # noqa: SLF001

    # ------------------------------------------------------------------
    # Mode entry / exit
    # ------------------------------------------------------------------

    def start(self) -> None:
        """Begin in Sleep Mode: only the wake listener is active."""
        self._enter_sleep("startup")

    def _enter_sleep(self, reason: str) -> None:
        with self._lock:
            self._active = False
            self._last_activity = None
            self._clear_context()
            if self._tts is not None:
                self._tts.disarm_barge_in()
            if self._wake is not None:
                self._wake.arm()
            # Sleep may be requested from any transient state (e.g. mid
            # PROCESSING on a sleep command); always settle to IDLE first so
            # the transition table is never violated.
            self._sm.on_idle(f"settle before sleep ({reason})")
            self._sm.to_sleep(f"sleep ({reason})")
        logger.info("Sleep Mode entered (%s)", reason)

    def _enter_conversation(self, reason: str) -> None:
        with self._lock:
            self._active = True
            self._touch_activity()
            if self._wake is not None:
                self._wake.disarm()
            if self._activity is not None:
                self._activity.reset()
            self._sm.on_wake_detected(f"wake ({reason})")
        logger.info("Conversation Mode entered (%s)", reason)

    @property
    def active(self) -> bool:
        return self._active

    @property
    def state(self) -> VoiceState:
        return self._sm.state

    # ------------------------------------------------------------------
    # Wake path
    # ------------------------------------------------------------------

    def _record_wake_latency(self, latency_ms: float) -> None:
        if self._request is not None:
            self._request.mark("wake_detected")
        logger.info("Wake latency: %.1f ms", latency_ms)

    def _on_wake(self, audio_data: object) -> None:
        """Wake phrase confirmed (mic thread).  If mid-speech -> barge-in."""
        logger.info("ConversationManager: wake confirmed")
        if self._tts is not None and self._tts.is_speaking:
            logger.info("ConversationManager: wake while speaking -> barge-in")
            self._tts.stop(reason="wake_while_speaking")
            self._sm.on_idle("wake barge-in")
            return
        self._start_request()
        self._enter_conversation("wake word")
        self._sm.on_listening("awaiting command")
        if self._tts is not None:
            self._tts.speak(self._acknowledge)
        if self._activity is not None:
            self._activity.begin(no_speech_timeout=self._conversation_timeout)

    def _start_request(self) -> None:
        self._request = RequestLogRecord()
        self._request.mark("wake_detected")

    # ------------------------------------------------------------------
    # Feed (called by AudioCapture on the mic thread)
    # ------------------------------------------------------------------

    def feed(self, clean_chunk: bytes) -> None:
        """Route a cleaned mic chunk based on the current state."""
        if not self._active:
            if self._wake is not None:
                self._wake.feed(clean_chunk)
            return
        if self._activity is not None:
            self._activity.process_audio(clean_chunk)
        if self._recognizer is not None:
            partial = self._recognizer.push(clean_chunk)
            if partial and self._on_partial is not None:
                try:
                    self._on_partial(partial)
                except Exception as exc:
                    logger.error("on_partial failed: %s", exc, exc_info=True)

    # ------------------------------------------------------------------
    # Command lifecycle
    # ------------------------------------------------------------------

    def on_speech_started(self) -> None:
        """User began speaking — flip to LISTENING (may interrupt TTS)."""
        with self._lock:
            if self._tts is not None and self._tts.is_speaking:
                logger.info("ConversationManager: speech during TTS -> interrupt")
                self._tts.stop(reason="user_barge_in")
            if self._request is not None:
                self._request.mark("speech_started")
            self._sm.on_listening("speech started")

    def on_speech_ended(self) -> None:
        """User stopped speaking — finalize ASR and process the command."""
        with self._lock:
            if self._request is not None:
                self._request.mark("speech_ended")
            self._sm.on_processing("speech ended")
        if self._recognizer is None:
            return
        result = self._recognizer.finalize()
        if self._request is not None:
            self._request.confidence = result.confidence
            self._request.recognized_text = result.text
        if not result.accepted:
            logger.info("Speech rejected (%s) — asking to repeat", result.reason)
            self._request.rejected_reason = result.reason if self._request else ""
            self._finish_request(accepted=False)
            if self._tts is not None:
                self._tts.speak(f"I didn't catch that. Please repeat. ({result.reason})")
            self._sm.on_idle("repeat prompt")
            self._begin_next_listen()
            return

        if is_sleep_phrase(result.text):
            self._handle_sleep_command(result.text)
            return

        self._process_command(result.text, result.confidence)

    def _handle_sleep_command(self, text: str) -> None:
        logger.info("ConversationManager: sleep command '%s'", text)
        if self._request is not None:
            self._request.recognized_text = text
            self._request.accepted = True
            self._request.intent = "exit"
        self._finish_request(accepted=True)
        if self._tts is not None:
            self._tts.cancel_all()
            self._tts.speak(self._sleep_response)
        self._enter_sleep("sleep command")

    def _process_command(self, text: str, confidence: float) -> None:
        self._touch_activity()
        decision = self._llm.route(
            text, confidence=confidence, accepted=True
        ) if self._llm is not None else None
        if decision is not None and not decision.invoked:
            # Gate rejected the input (should not happen after ASR accepted,
            # but guard anyway) — ask the user to repeat.
            if self._request is not None:
                self._request.rejected_reason = decision.rejected_reason
            self._finish_request(accepted=False)
            if self._tts is not None:
                self._tts.speak(
                    "I couldn't determine the requested action. Could you rephrase it?"
                )
            self._sm.on_idle("routing failed")
            self._begin_next_listen()
            return

        self._sm.on_thinking("command accepted")
        response = self._dispatch_command(text, confidence)
        self._remember_from_response(response)
        if self._request is not None and self._llm is not None:
            intent, action = self._llm.extract(response)
            self._request.intent = intent
            self._request.action_selected = action
        self._sm.on_speaking("responding")
        self._present_response(response)

    def _dispatch_command(self, text: str, confidence: float) -> Any:
        if self._dispatcher is None:
            return None
        result = self._dispatcher.dispatch(text, confidence)
        return result.response if result is not None else None

    def _record_stage(self, name: str, started_at: float) -> None:
        """Capture ``llm_ms`` / ``execution_ms`` from the worker thread."""
        record = self._request
        if record is not None:
            record.elapsed(name, started_at)

    def _present_response(self, response: Any) -> None:
        if response is None:
            return
        try:
            message = getattr(response, "voice_text", None)
            text = message() if callable(message) else getattr(response, "message", "")
        except Exception:
            text = getattr(response, "message", "")
        if text and self._tts is not None:
            self._tts.cancel_all()
            self._tts.speak(str(text))
        needs_confirm = bool(getattr(response, "needs_clarification", False))
        self._sm.on_idle("response presented" if not needs_confirm else "waiting confirmation")
        self._finish_request(accepted=True)
        self._begin_next_listen()

    def _begin_next_listen(self) -> None:
        """Re-arm listening for the next follow-up command."""
        with self._lock:
            self._touch_activity()
            if self._activity is not None:
                self._activity.reset()
                self._activity.begin(no_speech_timeout=self._conversation_timeout)
            self._sm.on_listening("awaiting next command")

    def _finish_request(self, accepted: bool) -> None:
        record = self._request
        self._request = None
        if record is not None:
            record.accepted = accepted
            record.finish()
            record.emit()

    # ------------------------------------------------------------------
    # Timer / sleep guard
    # ------------------------------------------------------------------

    def _touch_activity(self) -> None:
        self._last_activity = time.monotonic()

    def reset_activity(self) -> None:
        with self._lock:
            self._touch_activity()

    @property
    def seconds_until_sleep(self) -> float:
        if not self._active or self._last_activity is None:
            return 0.0
        return max(0.0, self._conversation_timeout - (time.monotonic() - self._last_activity))

    @property
    def timer_expired(self) -> bool:
        return self._active and self._last_activity is not None and (
            time.monotonic() - self._last_activity
        ) >= self._conversation_timeout

    def _no_false_sleep_guard(self) -> bool:
        """True when it is safe to sleep (nothing speaking/executing/loading).

        The guard is intentionally conservative: any pending activity, speech,
        queued TTS, or in-progress dispatch blocks Sleep Mode.
        """
        if self._activity is not None and self._activity.speaking:
            logger.info("Sleep guard: user still speaking")
            return False
        if self._tts is not None and self._tts.is_busy:
            logger.info("Sleep guard: TTS still speaking/queued")
            return False
        if self._dispatcher is not None and getattr(
            self._dispatcher, "_busy", False
        ):
            logger.info("Sleep guard: command still executing")
            return False
        return True

    def check_timeout(self) -> bool:
        """Call periodically (e.g. from the backend loop).

        Returns True when the machine transitioned back to Sleep Mode.
        """
        if not self._active:
            return False
        if not self.timer_expired:
            return False
        if not self._no_false_sleep_guard():
            # Keep listening; the timer can only trip once everything settles.
            self.reset_activity()
            return False
        logger.info("Conversation timer expired (%.0fs of silence) — sleeping",
                    self._conversation_timeout)
        if self._tts is not None:
            self._tts.speak(self._sleep_response)
        self._enter_sleep("timer expired")
        return True

    # ------------------------------------------------------------------
    # Context memory (temporary, cleared on sleep)
    # ------------------------------------------------------------------

    def remember(self, key: str, value: str) -> None:
        key = key.strip().casefold()
        if key not in _CONTEXT_KEYS:
            return
        with self._lock:
            self._context[key] = str(value)

    def _remember_from_response(self, response: Any) -> None:
        if response is None:
            return
        data = getattr(response, "data", None) or {}
        for key in _CONTEXT_KEYS:
            value = data.get(key) or data.get(key.replace("last_", ""))
            if value:
                self.remember(key, value)

    def context(self) -> dict[str, str]:
        with self._lock:
            return dict(self._context)

    def _clear_context(self) -> None:
        self._context = {}

    # ------------------------------------------------------------------

    @property
    def on_partial(self):
        return getattr(self, "_on_partial", None)

    def set_on_partial(self, callback: Callable[[str], None] | None) -> None:
        self._on_partial = callback

    def shutdown(self) -> None:
        """Stop everything and return to a silent, unarmed state."""
        with self._lock:
            self._active = False
        if self._wake is not None:
            try:
                self._wake.shutdown()
            except Exception:
                pass
        if self._tts is not None:
            try:
                self._tts.shutdown()
            except Exception:
                pass
        if self._audio is not None:
            try:
                self._audio.shutdown()
            except Exception:
                pass
        self._sm.reset(VoiceState.SLEEP, "shutdown")
        logger.info("ConversationManager shut down")