"""
services/silence_gate.py — shared "silence / noise / garbage" detector (PART 13).

A capture result that is silent, noisy, empty, cancelled, or a decoder
run-away (pathological repetition) must NEVER start a repeat / confirmation
loop: it returns to wake/idle quietly.  Only meaningful speech may prompt.

Both the wake-capture loop and the active-conversation loop in
``conversation_owner`` use this single helper so the two paths stay in sync.
"""
from __future__ import annotations

# Reasons that are NOT "I didn't understand you" situations.  Anything in
# this set means: go quiet, do not ask to repeat.
_QUIET_REASONS = frozenset({
    "no speech recognized",
    "pathological repetition",
    "too short",
    "cancelled",
})


def is_silence_or_garbage(text: str | None, reason: str | None) -> bool:
    """Return True when a capture result must not start a repeat loop.

    True (quiet) for: empty/missing text, a cancelled capture, and the
    rejection reasons that indicate silence, noise, or a decoder run-away.
    False only for a real utterance that the recognizer heard but did not
    understand (e.g. ``low confidence``), which is allowed one repeat ask.
    """
    if not text or not text.strip():
        return True
    if reason in _QUIET_REASONS:
        return True
    return False
