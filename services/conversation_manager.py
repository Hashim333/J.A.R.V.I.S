from __future__ import annotations

import enum
import logging
import re
import time
from typing import Any

from thinking.confirmation import ConfirmationEngine

logger = logging.getLogger(__name__)


class ConversationState(enum.Enum):
    STANDBY = "STANDBY"
    IDLE = "IDLE"
    WAKE_DETECTED = "WAKE_DETECTED"
    LISTENING = "LISTENING"
    THINKING = "THINKING"
    SPEAKING = "SPEAKING"
    WAITING_CONFIRMATION = "WAITING_CONFIRMATION"
    EXECUTING = "EXECUTING"
    ACTIVE_CONVERSATION = "ACTIVE_CONVERSATION"
    TIMEOUT = "TIMEOUT"
    RETURN_TO_IDLE = "RETURN_TO_IDLE"


_EXIT_PHRASES: list[re.Pattern] = [
    re.compile(r"^\s*(?:exit|end|stop|finish)\s+conversation\s*$", re.IGNORECASE),
    re.compile(r"^\s*stop\s+listening\s*$", re.IGNORECASE),
    re.compile(r"^\s*thank\s*you\s*(?:goodbye|bye)\s*$", re.IGNORECASE),
    re.compile(r"^\s*(?:go\s+)?idle\s*$", re.IGNORECASE),
    re.compile(r"^\s*sleep\s*$", re.IGNORECASE),
    re.compile(r"^\s*never\s*mind\s*$", re.IGNORECASE),
]


def is_exit_command(text: str) -> bool:
    for pattern in _EXIT_PHRASES:
        if pattern.match(text.strip()):
            return True
    return False


class ConversationManager:
    def __init__(
        self,
        activity_timeout: float = 45.0,
        confirmation_timeout: float = 15.0,
        wake_word_service: Any | None = None,
    ) -> None:
        self._activity_timeout = activity_timeout
        self._confirmation_timeout = confirmation_timeout
        self._state = ConversationState.STANDBY
        self._default_timeout = 30.0
        self._last_activity: float | None = None
        self._confirmation_engine = ConfirmationEngine()
        self._pending_intent: str | None = None
        self._pending_entities: dict | None = None
        self._pending_raw_text: str | None = None
        self._paused = False
        self._pause_reason = ""
        self._last_interruption_reason = ""
        self._context_memory: dict[str, Any] = {}
        self._context_history: list[dict[str, Any]] = []
        self._wake_word_service = wake_word_service

    @property
    def state(self) -> ConversationState:
        return self._state

    def _set_state(self, new: ConversationState, reason: str = "") -> None:
        if self._state == new:
            return
        old = self._state
        self._state = new
        msg = f"STATE {old.value} -> {new.value}"
        if reason:
            msg += f" ({reason})"
        logger.info(msg)

    # ── State transitions ──────────────────────────────────────────

    def on_wake_word(self) -> None:
        self._set_state(ConversationState.WAKE_DETECTED, "wake word heard")

    def on_listening(self) -> None:
        self._set_state(ConversationState.LISTENING)

    def on_command_received(self) -> None:
        self._touch_activity()
        self._set_state(ConversationState.THINKING)

    def transition_to_active(self, reason: str = "") -> None:
        # Always refresh the activity clock — repeated calls (one per command
        # in a conversation) must keep extending the window, not no-op.
        self._touch_activity()
        if self._state == ConversationState.ACTIVE_CONVERSATION:
            return
        self._set_state(ConversationState.ACTIVE_CONVERSATION, reason or "active conversation")
        if self._wake_word_service is not None:
            try:
                self._wake_word_service.stop()
            except Exception:
                pass

    def transition_to_standby(self, reason: str = "") -> None:
        if self._state == ConversationState.STANDBY:
            return
        self._clear_pending()
        self._last_activity = None
        self._set_state(ConversationState.STANDBY, reason or "standby")
        if self._wake_word_service is not None:
            try:
                self._wake_word_service.reset_for_wake()
            except Exception:
                pass

    def on_speaking(self) -> None:
        self._set_state(ConversationState.SPEAKING)

    def on_executing(self) -> None:
        self._set_state(ConversationState.EXECUTING)

    def enter_active_conversation(self, reason: str = "") -> None:
        self._touch_activity()
        self._set_state(ConversationState.ACTIVE_CONVERSATION, reason)

    def return_to_idle(self, reason: str = "") -> None:
        self._clear_pending()
        self._set_state(ConversationState.RETURN_TO_IDLE, reason)
        self._state = ConversationState.IDLE
        self._rearm_wake("return to idle")
        logger.info("Sleep entered — returning to wake mode (%s)", reason or "idle")

    def on_timeout(self) -> None:
        self._clear_pending()
        self._set_state(ConversationState.TIMEOUT)
        self._state = ConversationState.IDLE
        self._rearm_wake("timeout")

    def _rearm_wake(self, context: str) -> None:
        """Re-arm the wake-word service whenever the conversation leaves the
        engaged states, so the assistant is always wakeable again."""
        if self._wake_word_service is not None:
            try:
                self._wake_word_service.reset_for_wake()
            except Exception as exc:
                logger.error("Failed to re-arm wake word service (%s): %s", context, exc)

    # ── Confirmation helpers ───────────────────────────────────────

    def request_confirmation(self, intent: str, entities: dict, raw_text: str) -> str:
        self._pending_intent = intent
        self._pending_entities = entities
        self._pending_raw_text = raw_text
        self._touch_activity()
        self._set_state(ConversationState.WAITING_CONFIRMATION, intent)
        return self._confirmation_engine.build_question(intent, entities)

    def classify_confirmation(self, answer: str) -> str:
        return self._confirmation_engine.classify_answer(answer)

    @property
    def has_pending_confirmation(self) -> bool:
        return self._pending_intent is not None

    def resume_pending(self) -> tuple[str, dict, str] | None:
        if not self.has_pending_confirmation:
            return None
        return (self._pending_intent, self._pending_entities, self._pending_raw_text)

    def pause(self, reason: str = "") -> None:
        self._paused = True
        self._pause_reason = reason.strip()
        self._last_interruption_reason = self._pause_reason or "interrupted"
        self._touch_activity()
        self._record_context("pause", self._last_interruption_reason)

    def resume(self, reason: str = "") -> None:
        self._paused = False
        self._pause_reason = ""
        if reason:
            self._last_interruption_reason = reason.strip()
        self._record_context("resume", self._last_interruption_reason or "resumed")

    @property
    def is_paused(self) -> bool:
        return self._paused

    @property
    def last_interruption_reason(self) -> str:
        return self._last_interruption_reason

    def remember_context(self, key: str, value: Any) -> None:
        self._context_memory[str(key)] = value
        self._record_context("memory", {str(key): value})

    def get_context_memory(self) -> dict[str, Any]:
        return dict(self._context_memory)

    def _clear_pending(self) -> None:
        self._pending_intent = None
        self._pending_entities = None
        self._pending_raw_text = None

    def _record_context(self, event: str, payload: Any) -> None:
        self._context_history.append({"event": event, "payload": payload})

    # ── Activity / timeout ─────────────────────────────────────────

    def _touch_activity(self) -> None:
        self._last_activity = time.monotonic()

    def reset_activity(self) -> None:
        self._last_activity = time.monotonic()

    @property
    def is_expired(self) -> bool:
        if self._state == ConversationState.STANDBY:
            return False
        if self._last_activity is None:
            return False
        timeout = self._confirmation_timeout if self._state == ConversationState.WAITING_CONFIRMATION else self._activity_timeout
        return (time.monotonic() - self._last_activity) >= timeout

    @property
    def remaining_time(self) -> float:
        if self._state == ConversationState.STANDBY:
            return self._default_timeout
        if self._last_activity is None:
            return self._activity_timeout
        timeout = (
            self._confirmation_timeout
            if self._state == ConversationState.WAITING_CONFIRMATION
            else self._activity_timeout
        )
        return max(0.0, timeout - (time.monotonic() - self._last_activity))

    # ── Static helpers ─────────────────────────────────────────────

    @staticmethod
    def is_exit_command(text: str) -> bool:
        return is_exit_command(text)

    @staticmethod
    def is_sleep_command(text: str) -> bool:
        if not isinstance(text, str):
            return False
        stripped = text.strip().casefold()
        if not stripped:
            return False
        return stripped in {
            "go to sleep",
            "sleep",
            "stop listening",
            "stand by",
            "goodbye",
            "exit conversation",
            "bye",
        } or stripped.startswith("go to sleep")
