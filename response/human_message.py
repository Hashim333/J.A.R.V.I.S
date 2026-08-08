"""
response/human_message.py

Human-language message table for the Human Conversation Layer.

Every internal state maps to a calm, natural phrase that is safe to
speak to the user. Technical detail (timeout values, WinError numbers,
exception names, paths, model names, raw logs) must never appear in any
of these messages.
"""

from __future__ import annotations

from enum import Enum
from typing import Any

# -- Canonical internal-state keys -------------------------------------
TimeoutError = "TimeoutError"
SpeechRecognitionLowConfidence = "SpeechRecognitionLowConfidence"
NoSpeechDetected = "NoSpeechDetected"
PermissionDenied = "PermissionDenied"
AutomationUnavailable = "AutomationUnavailable"
LLMUnavailable = "LLMUnavailable"
InternetUnavailable = "InternetUnavailable"
UnknownCommand = "UnknownCommand"
Misheard = "Misheard"
UnexpectedError = "UnexpectedError"


HUMAN_MESSAGES: dict[str, str] = {
    TimeoutError: (
        "I'm sorry, sir. I'm taking longer than expected. "
        "Could you try asking again?"
    ),
    SpeechRecognitionLowConfidence: (
        "I'm not completely sure what you said. Could you repeat that?"
    ),
    NoSpeechDetected: "I didn't hear anything.",
    PermissionDenied: "Windows needs administrator permission for that task.",
    AutomationUnavailable: "I haven't learned how to do that yet.",
    LLMUnavailable: "I'm having trouble thinking right now.",
    InternetUnavailable: "I'm currently offline. I can still help with local tasks.",
    UnknownCommand: "I'm sorry, sir. I couldn't determine the requested action.",
    Misheard: "I'm sorry, sir. Could you repeat that?",
    UnexpectedError: "I'm sorry, sir. Something went wrong. Could you try again?",
}

SAFE_FALLBACK: str = "I'm sorry, sir. Could you try again?"


class InternalState(str, Enum):
    """Canonical internal-state keys understood by the Human Layer."""

    TIMEOUT = TimeoutError
    LOW_CONFIDENCE = SpeechRecognitionLowConfidence
    NO_SPEECH = NoSpeechDetected
    PERMISSION_DENIED = PermissionDenied
    AUTOMATION_UNAVAILABLE = AutomationUnavailable
    LLM_UNAVAILABLE = LLMUnavailable
    INTERNET_UNAVAILABLE = InternetUnavailable
    UNKNOWN_COMMAND = UnknownCommand
    MISHEARD = Misheard
    UNEXPECTED_ERROR = UnexpectedError


def classify(state: Any) -> str:
    """Best-effort classification of an exception or state token.

    Returns a canonical key from :data:`HUMAN_MESSAGES`, or ``""`` when
    the input cannot be classified by name alone.
    """
    if isinstance(state, str):
        name = state.strip()
        if name in HUMAN_MESSAGES:
            return name
        lowered = name.casefold()
        if lowered in _ALIASES:
            return _ALIASES[lowered]
        return ""

    exc_type = type(state)
    name = exc_type.__name__
    for candidate in (
        name,
        exc_type.__qualname__,
        getattr(state, "__class__", exc_type).__name__,
    ):
        if candidate in HUMAN_MESSAGES:
            return candidate

    lowered = name.casefold()
    if lowered in _ALIASES:
        return _ALIASES[lowered]

    for cls in _MRO_OF(state):
        cls_name = cls.__name__
        if cls_name in _EXCEPTION_KEY_MAP:
            return _EXCEPTION_KEY_MAP[cls_name]

    for prefix, key in _PREFIX_ALIASES:
        if lowered.startswith(prefix):
            return key

    return ""


_ALIASES: dict[str, str] = {
    "lowconfidence": SpeechRecognitionLowConfidence,
    "low_confidence": SpeechRecognitionLowConfidence,
    "low-confidence": SpeechRecognitionLowConfidence,
    "low confidence": SpeechRecognitionLowConfidence,
    "confidence_too_low": SpeechRecognitionLowConfidence,
    "confidence": SpeechRecognitionLowConfidence,
    "no_speech": NoSpeechDetected,
    "no speech": NoSpeechDetected,
    "nospeechdetected": NoSpeechDetected,
    "nospeech": NoSpeechDetected,
    "permission": PermissionDenied,
    "permissionerror": PermissionDenied,
    "winerror": PermissionDenied,
    "accessdenied": PermissionDenied,
    "access_denied": PermissionDenied,
    "denied": PermissionDenied,
    "automationunavailable": AutomationUnavailable,
    "automation unavailable": AutomationUnavailable,
    "automation_not_available": AutomationUnavailable,
    "not_implemented": AutomationUnavailable,
    "unsupportedoperation": AutomationUnavailable,
    "llmunavailable": LLMUnavailable,
    "llm_unavailable": LLMUnavailable,
    "llm unavailable": LLMUnavailable,
    "offline": InternetUnavailable,
    "internetunavailable": InternetUnavailable,
    "internet unavailable": InternetUnavailable,
    "connectionerror": InternetUnavailable,
    "networkunavailable": InternetUnavailable,
    "unknowncommand": UnknownCommand,
    "unknown command": UnknownCommand,
    "unknowncommand": UnknownCommand,
    "misheard": Misheard,
    "unrecognized": Misheard,
    "unrecognized_speech": Misheard,
    "genericerror": UnexpectedError,
    "unexpectederror": UnexpectedError,
    "unexpected error": UnexpectedError,
}


_EXCEPTION_KEY_MAP: dict[str, str] = {
    "TimeoutError": TimeoutError,
    "TimeoutExpired": TimeoutError,
    "asyncio.TimeoutError": TimeoutError,
    "PermissionError": PermissionDenied,
    "OSError": PermissionDenied,
    "WinError": PermissionDenied,
    "ConnectionError": InternetUnavailable,
    "TimeoutException": TimeoutError,
}


_PREFIX_ALIASES: tuple[tuple[str, str], ...] = (
    ("timeout", TimeoutError),
    ("timed out", TimeoutError),
    ("no speech", NoSpeechDetected),
    ("low confidence", SpeechRecognitionLowConfidence),
    ("permission", PermissionDenied),
    ("access denied", PermissionDenied),
    ("unknown command", UnknownCommand),
    ("offline", InternetUnavailable),
    ("internet", InternetUnavailable),
    ("llm", LLMUnavailable),
    ("automation", AutomationUnavailable),
)


def _MRO_OF(state: Any) -> list[type]:
    try:
        return list(type(state).__mro__)
    except Exception:
        return []


def is_known_state(state: Any) -> bool:
    return classify(state) in HUMAN_MESSAGES