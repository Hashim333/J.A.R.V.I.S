from __future__ import annotations

from enum import Enum


class Intent(Enum):
    CONFIRM = "CONFIRM"
    DECLINE = "DECLINE"
    NEW_WINDOW = "NEW_WINDOW"
    SLEEP = "SLEEP"
    HELP = "HELP"
    EXIT = "EXIT"
    CANCEL = "CANCEL"
    UNKNOWN = "UNKNOWN"
    # FIX-VOICE-003: conversational intent for "can you hear me?"
    CONVERSATIONAL = "CONVERSATIONAL"


_NORMALIZER_MAP: dict[frozenset[str], Intent] = {
    frozenset({"yes", "yeah", "yep", "ok", "okay", "go ahead", "continue", "confirm", "sure", "do it", "proceed", "indeed", "affirmative", "correct"}): Intent.CONFIRM,
    frozenset({"no", "cancel", "stop", "don't", "never mind", "nope", "nah", "negative", "abort", "halt", "forget it", "dismiss", "decline"}): Intent.DECLINE,
    frozenset({"new", "new window", "another window", "another one", "open separately", "fresh window", "separate window", "new one", "another", "a new one"}): Intent.NEW_WINDOW,
    frozenset({"go to sleep", "sleep", "stand by", "stop listening", "goodbye", "exit conversation", "deactivate", "pause", "take a break"}): Intent.SLEEP,
    frozenset({"help", "what can you do", "commands", "what do you do", "options", "capabilities"}): Intent.HELP,
    frozenset({"exit", "quit", "shutdown", "turn off", "close", "bye"}): Intent.EXIT,
}

# FIX-VOICE-003: deterministic conversational intent patterns
_CONVERSATIONAL_PATTERNS = {
    "can you hear me",
    "can you hear me?",
    "are you there",
    "are you listening",
    "jarvis can you hear me",
    "jarvis are you there",
    "jarvis are you listening",
}


def normalize(text: str) -> Intent:
    normalized = text.casefold().strip()
    normalized = _strip_punctuation(normalized)
    
    # FIX-VOICE-003: check for deterministic conversational patterns first
    if normalized in _CONVERSATIONAL_PATTERNS:
        return Intent.CONVERSATIONAL
    
    for phrases, intent in _NORMALIZER_MAP.items():
        if normalized in phrases:
            return intent
    return Intent.UNKNOWN


def _strip_punctuation(text: str) -> str:
    result = []
    for ch in text:
        if ch.isalnum() or ch in ("'", " ", "-"):
            result.append(ch)
    return "".join(result).strip()
