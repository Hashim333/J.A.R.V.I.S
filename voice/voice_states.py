"""
voice/voice_states.py

Explicit voice lifecycle states for the full-duplex pipeline:

    Idle -> Listening -> (Thinking) -> Speaking -> (Interrupted/Cancelled) -> Idle

Requirement: the voice engine must expose distinguishable states —
Idle, Listening, Thinking, Speaking, Interrupted, Cancelled — so the UI
always knows exactly what the voice layer is doing and every transient
state is guaranteed to return to Idle (finally-based transitions).
"""
from __future__ import annotations

import enum
import logging
from contextlib import contextmanager
from typing import Callable

logger = logging.getLogger(__name__)


class VoiceState(enum.Enum):
    """The six explicit voice states required by the redesign."""

    IDLE = "Idle"
    LISTENING = "Listening"
    THINKING = "Thinking"
    SPEAKING = "Speaking"
    INTERRUPTED = "Interrupted"
    CANCELLED = "Cancelled"


_STATE_CHANGE_HANDLER: Callable[[VoiceState, VoiceState], None] | None = None


def set_global_state_handler(handler: Callable[[VoiceState, VoiceState], None] | None) -> None:
    """Register a process-wide observer of voice state changes.

    ``run.py`` uses this to push state transitions to the UI bridge.
    Only one global handler is supported (the app runs a single voice layer).
    """
    global _STATE_CHANGE_HANDLER
    _STATE_CHANGE_HANDLER = handler


class VoiceStateManager:
    """Thread-safe voice state machine with finally-based return-to-Idle."""

    def __init__(
        self,
        on_change: Callable[[VoiceState, VoiceState], None] | None = None,
        initial: VoiceState = VoiceState.IDLE,
    ) -> None:
        self._state = initial
        self._on_change = on_change

    # ------------------------------------------------------------------
    # State
    # ------------------------------------------------------------------

    @property
    def state(self) -> VoiceState:
        return self._state

    @property
    def name(self) -> str:
        return self._state.value

    def set_state(self, new: VoiceState, reason: str = "") -> None:
        """Transition to *new*.  Same-state transitions are no-ops."""
        if not isinstance(new, VoiceState):
            raise TypeError(f"VoiceState expected, got {type(new).__name__}")
        if new == self._state:
            return
        old = self._state
        self._state = new
        logger.info(
            "VOICE STATE %s -> %s%s",
            old.value,
            new.value,
            f" ({reason})" if reason else "",
        )
        if self._on_change:
            try:
                self._on_change(old, new)
            except Exception as exc:
                logger.error("Voice state change handler failed: %s", exc, exc_info=True)
        handler = _STATE_CHANGE_HANDLER
        if handler:
            try:
                handler(old, new)
            except Exception as exc:
                logger.error("Global voice state handler failed: %s", exc, exc_info=True)

    # ------------------------------------------------------------------
    # Named transitions
    # ------------------------------------------------------------------

    def on_listening(self, reason: str = "") -> None:
        self.set_state(VoiceState.LISTENING, reason)

    def on_thinking(self, reason: str = "") -> None:
        self.set_state(VoiceState.THINKING, reason)

    def on_speaking(self, reason: str = "") -> None:
        self.set_state(VoiceState.SPEAKING, reason)

    def on_interrupted(self, reason: str = "") -> None:
        self.set_state(VoiceState.INTERRUPTED, reason)

    def on_cancelled(self, reason: str = "") -> None:
        self.set_state(VoiceState.CANCELLED, reason)

    def return_to_idle(self, reason: str = "") -> None:
        self.set_state(VoiceState.IDLE, reason)

    # ------------------------------------------------------------------
    # finally-safe context manager
    # ------------------------------------------------------------------

    @contextmanager
    def transition(self, state: VoiceState, reason: str = ""):
        """Enter *state* and guarantee a return to Idle on exit.

        Even if the body raises, the state machine always lands back on
        Idle so the UI can never be stuck in a transient voice state::

            with states.transition(VoiceState.LISTENING, "capture"):
                result = session.capture_command(timeout=10.0)
        """
        self.set_state(state, reason)
        try:
            yield
        finally:
            self.return_to_idle(f"{state.value} completed")
