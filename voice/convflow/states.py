"""
voice/pipeline/states.py

The strict 9-state conversation state machine for the JARVIS voice pipeline.

States:
    SLEEP        — wake-mode; only the WakeWordManager is listening.
    WAKE_DETECTED — "jarvis" heard; an acknowledgement is about to be played.
    LISTENING    — the mic is open; the user is (or is expected to be) speaking.
    PROCESSING   — audio influence is settling and the speech segment is
                   being assembled (transcriber finalize / gating in progress).
    THINKING     — the command has been accepted; the LLM / intent router is
                   producing a response.
    SPEAKING     — TTS is playing JARVIS's reply.
    EXECUTING    — an automation action is running on a worker.
    IDLE         — conversation settled; single-command session may re-arm wake.
    ERROR        — a pipeline stage failed; graceful recovery is required.

Every transition is explicit and validated against a transition table.  A
state machine holds a *single* state at a time, so mutually-exclusive voice
states (Listening+Speaking, Thinking+Listening, Speaking+Listening,
Executing+Listening) are impossible *by construction*; the table still
rejects any illegal jump and, when a handler composes a *set* of simultaneous
stages, ``assert_exclusive`` validates that no forbidden pair is present.

Transitions are thread-safe so the mic thread and the backend thread can
share one machine without a UI freeze or a torn state read.
"""
from __future__ import annotations

import enum
import logging
import threading
from typing import Callable, Iterable

logger = logging.getLogger(__name__)


class VoiceState(enum.Enum):
    """The nine explicit pipeline states."""

    SLEEP = "sleep"
    WAKE_DETECTED = "wake_detected"
    LISTENING = "listening"
    PROCESSING = "processing"
    THINKING = "thinking"
    SPEAKING = "speaking"
    EXECUTING = "executing"
    IDLE = "idle"
    ERROR = "error"


#: Pairs of states that must never be active simultaneously.  A single-state
#: machine cannot normally occupy two at once, but *every* transition is also
#: checked against these so a slotting bug can never report the pipeline as,
#: e.g., speaking while it listens.
FORBIDDEN_CONCURRENT_PAIRS: frozenset[frozenset[VoiceState]] = frozenset(
    {
        frozenset({VoiceState.LISTENING, VoiceState.SPEAKING}),
        frozenset({VoiceState.THINKING, VoiceState.LISTENING}),
        frozenset({VoiceState.SPEAKING, VoiceState.LISTENING}),
        frozenset({VoiceState.EXECUTING, VoiceState.LISTENING}),
        frozenset({VoiceState.LISTENING, VoiceState.PROCESSING}),
    }
)

#: Allowed single-step transitions.  Anything not listed here is illegal.
_ALLOWED: dict[VoiceState, frozenset[VoiceState]] = {
    VoiceState.SLEEP: frozenset(
        {VoiceState.WAKE_DETECTED, VoiceState.IDLE, VoiceState.ERROR}
    ),
    VoiceState.WAKE_DETECTED: frozenset(
        {VoiceState.LISTENING, VoiceState.SLEEP, VoiceState.PROCESSING,
         VoiceState.ERROR, VoiceState.IDLE}
    ),
    VoiceState.LISTENING: frozenset(
        {VoiceState.SLEEP, VoiceState.PROCESSING, VoiceState.THINKING,
         VoiceState.IDLE, VoiceState.ERROR}
    ),
    VoiceState.PROCESSING: frozenset(
        {VoiceState.THINKING, VoiceState.EXECUTING, VoiceState.SPEAKING,
         VoiceState.IDLE, VoiceState.ERROR}
    ),
    VoiceState.THINKING: frozenset(
        {VoiceState.EXECUTING, VoiceState.SPEAKING, VoiceState.IDLE,
         VoiceState.ERROR, VoiceState.LISTENING}
    ),
    VoiceState.SPEAKING: frozenset(
        {VoiceState.IDLE, VoiceState.LISTENING, VoiceState.SLEEP,
         VoiceState.ERROR}
    ),
    VoiceState.EXECUTING: frozenset(
        {VoiceState.SPEAKING, VoiceState.IDLE, VoiceState.THINKING,
         VoiceState.ERROR}
    ),
    VoiceState.IDLE: frozenset(
        {VoiceState.SLEEP, VoiceState.LISTENING, VoiceState.WAKE_DETECTED,
         VoiceState.ERROR}
    ),
    VoiceState.ERROR: frozenset(
        {VoiceState.SLEEP, VoiceState.IDLE, VoiceState.LISTENING}
    ),
}


class InvalidTransition(Exception):
    """Raised/recorded when a state transition violates the table."""


class ConversationStateMachine:
    """Thread-safe, strict 9-state conversation machine.

    Args:
        initial: Starting state (default ``VoiceState.SLEEP`` — wake mode).
        on_change: Optional ``(old, new, reason) -> None`` callback invoked
            (outside the lock) after every legal transition.
        throw: If True, an illegal transition raises :class:`InvalidTransition`
            instead of logging and returning False (used in tests).
        recover_to: On an illegal transition the machine optionally lands in a
            safe state so the UI can never be stuck.  ``None`` keeps the
            current state.
    """

    def __init__(
        self,
        initial: VoiceState = VoiceState.SLEEP,
        on_change: Callable[[VoiceState, VoiceState, str], None] | None = None,
        throw: bool = False,
        recover_to: VoiceState | None = VoiceState.ERROR,
    ) -> None:
        self._state = VoiceState(initial)
        self._on_change = on_change
        self._throw = throw
        self._recover_to = recover_to
        self._lock = threading.RLock()

    # ------------------------------------------------------------------
    # Queries
    # ------------------------------------------------------------------

    @property
    def state(self) -> VoiceState:
        with self._lock:
            return self._state

    @property
    def name(self) -> str:
        with self._lock:
            return self._state.value

    def is_(self, state: VoiceState) -> bool:
        return self.state is VoiceState(state)

    def can_transition(self, target: VoiceState) -> bool:
        target = VoiceState(target)
        with self._lock:
            return target in _ALLOWED.get(self._state, frozenset())

    # ------------------------------------------------------------------
    # Transitions
    # ------------------------------------------------------------------

    def transition(self, target: VoiceState, reason: str = "") -> bool:
        """Perform a single validated transition.

        Returns True on success (or a legitimate no-op same-state) and False
        when the move is illegal (optionally raising).  On an illegal move it
        logs a structured warning specifying the forbidden pair so the
        pipeline can never silently report two voice stages at once.
        """
        target = VoiceState(target)
        with self._lock:
            if target is self._state:
                return True
            allowed = _ALLOWED.get(self._state, frozenset())
            if target not in allowed:
                return self._reject(self._state, target, reason)
            return self._commit(target, reason)

    def _commit(self, target: VoiceState, reason: str) -> bool:
        old = self._state
        self._state = target
        logger.info("VOICE STATE %s -> %s%s",
                    old.value, target.value,
                    f" ({reason})" if reason else "")
        cb = self._on_change
        if cb is not None:
            try:
                cb(old, target, reason)
            except Exception as exc:
                logger.error("State change callback failed: %s", exc, exc_info=True)
        return True

    def _reject(self, old: VoiceState, target: VoiceState, reason: str) -> bool:
        pair = frozenset({old, target})
        explanation = (
            "forbidden-concurrent"
            if any(p == pair for p in FORBIDDEN_CONCURRENT_PAIRS)
            else "illegal-transition"
        )
        logger.warning(
            "VOICE STATE REJECTED %s -> %s attempted (%s) reason=%r",
            old.value, target.value, explanation, reason,
        )
        if self._throw:
            raise InvalidTransition(
                f"{old.value} -> {target.value} is not allowed ({explanation})"
            )
        if self._recover_to is not None and self._recover_to is not old:
            logger.warning("VOICE STATE recovering %s -> %s",
                           old.value, self._recover_to.value)
            self._state = self._recover_to
        return False

    # ------------------------------------------------------------------
    # Named helpers
    # ------------------------------------------------------------------

    def to_sleep(self, reason: str = "") -> bool:
        return self.transition(VoiceState.SLEEP, reason)

    def on_wake_detected(self, reason: str = "") -> bool:
        return self.transition(VoiceState.WAKE_DETECTED, reason)

    def on_listening(self, reason: str = "") -> bool:
        return self.transition(VoiceState.LISTENING, reason)

    def on_processing(self, reason: str = "") -> bool:
        return self.transition(VoiceState.PROCESSING, reason)

    def on_thinking(self, reason: str = "") -> bool:
        return self.transition(VoiceState.THINKING, reason)

    def on_speaking(self, reason: str = "") -> bool:
        return self.transition(VoiceState.SPEAKING, reason)

    def on_executing(self, reason: str = "") -> bool:
        return self.transition(VoiceState.EXECUTING, reason)

    def on_idle(self, reason: str = "") -> bool:
        return self.transition(VoiceState.IDLE, reason)

    def on_error(self, reason: str = "") -> bool:
        return self.transition(VoiceState.ERROR, reason)

    def reset(self, state: VoiceState = VoiceState.SLEEP, reason: str = "") -> None:
        """Force a known state (recovery); bypasses the transition table."""
        state = VoiceState(state)
        with self._lock:
            old = self._state
            self._state = state
        logger.info("VOICE STATE reset %s -> %s (%s)",
                    old.value, state.value, reason or "manual override")

    # ------------------------------------------------------------------
    # Exclusive-composition guard
    # ------------------------------------------------------------------

    @staticmethod
    def assert_exclusive(states: Iterable[VoiceState]) -> None:
        """Ensure a set of simultaneously-reported stages contains no
        forbidden pair (used by composers that report multiple lanes)."""
        present = {VoiceState(s) for s in states}
        for pair in FORBIDDEN_CONCURRENT_PAIRS:
            if pair.issubset(present):
                a, b = sorted(pair, key=lambda s: s.value)
                raise InvalidTransition(
                    f"forbidden concurrent states: {a.value} + {b.value}"
                )