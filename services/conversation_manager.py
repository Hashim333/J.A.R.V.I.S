"""
services/conversation_manager.py

Manages JARVIS conversation states: STANDBY (wake word only) and
ACTIVE_CONVERSATION (continuous command listening without wake word).

State diagram:

    ┌──────────┐     wake word detected     ┌────────────────────┐
    │  STANDBY  │ ──────────────────────────> │ ACTIVE_CONVERSATION │
    │           │                             │                    │
    │ wake word │     sleep command           │  continuous listen │
    │  only     │ <────────────────────────── │  30s timeout       │
    └──────────┘     critical error           └────────────────────┘
"""

from __future__ import annotations

import enum
import logging
import time

from services.listener_service import ListenerService
from services.wake_word_service import WakeWordService

logger = logging.getLogger(__name__)

_SLEEP_PHRASES = frozenset({
    "go to sleep",
    "sleep",
    "stand by",
    "stop listening",
    "goodbye",
    "exit conversation",
})


class ConversationState(enum.Enum):
    STANDBY = "STANDBY"
    ACTIVE_CONVERSATION = "ACTIVE_CONVERSATION"


class ConversationManager:
    """
    Conversation state machine for JARVIS.

    Owns the state transitions between STANDBY and ACTIVE_CONVERSATION,
    manages the inactivity timer, and provides helpers for sleep-command
    detection.

    The microphone stream stays running across all transitions — only
    the audio consumer on the stream is swapped.
    """

    def __init__(
        self,
        wake_word_service: WakeWordService,
        listener_service: ListenerService,
        activity_timeout: float = 30.0,
    ) -> None:
        self._wake_word_service = wake_word_service
        self._listener_service = listener_service
        self._activity_timeout = activity_timeout
        self._state = ConversationState.STANDBY
        self._last_activity: float | None = None

    @property
    def state(self) -> ConversationState:
        return self._state

    def transition_to_active(self) -> None:
        """Move from STANDBY to ACTIVE_CONVERSATION."""
        if self._state == ConversationState.ACTIVE_CONVERSATION:
            return
        self._state = ConversationState.ACTIVE_CONVERSATION
        self._last_activity = time.monotonic()
        self._wake_word_service.stop()
        logger.info("STATE -> %s", self._state.value)

    def transition_to_standby(self, reason: str = "") -> None:
        """Move from ACTIVE_CONVERSATION back to STANDBY."""
        if self._state == ConversationState.STANDBY:
            return
        self._state = ConversationState.STANDBY
        self._last_activity = None
        self._wake_word_service.reset_for_wake()
        msg = "STATE -> STANDBY"
        if reason:
            msg += f" ({reason})"
        logger.info(msg)

    def reset_activity(self) -> None:
        """Reset the inactivity timer — call after processing a command."""
        self._last_activity = time.monotonic()

    @property
    def is_expired(self) -> bool:
        """True if the inactivity timeout has been exceeded."""
        if self._state != ConversationState.ACTIVE_CONVERSATION or self._last_activity is None:
            return False
        return (time.monotonic() - self._last_activity) >= self._activity_timeout

    @property
    def remaining_time(self) -> float:
        """Seconds before timeout (0 if already expired)."""
        if self._state != ConversationState.ACTIVE_CONVERSATION or self._last_activity is None:
            return self._activity_timeout
        return max(0.0, self._activity_timeout - (time.monotonic() - self._last_activity))

    @staticmethod
    def is_sleep_command(text: str) -> bool:
        """Check whether text is a deactivation/sleep command."""
        return text.casefold().strip() in _SLEEP_PHRASES
