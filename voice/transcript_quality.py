"""
voice/transcript_quality.py — reusable transcript validation.

Small, dependency-free helpers shared by the STT gate (``voice/whisper_stt``),
the Speech Intelligence Layer (``thinking/speech_intelligence``) and the
capture path (``voice/duplex``) for the voice-reliability milestone:

  * pathological-repetition detection — the classic Whisper hallucination
    shapes ("I'm sorry I'm sorry I'm sorry...", "play music play music ..."),
  * a conservative known-command corroboration check (verb + known app /
    known canonical command) used to rescue *low-confidence but clean* short
    commands WITHOUT lowering the numeric confidence thresholds globally.

The app / verb / command tables below mirror the deterministic parser's own
tables (``brain/parser`` ``_APP_SYNONYMS`` / ``_OPEN_VERBS`` and the
``voice/synonym_engine`` canonical map) so the voice path and the parser
agree on what a "known command" looks like (PART 14).
"""
from __future__ import annotations

import re

# Known canonical app aliases — aligned with ``brain/parser._APP_SYNONYMS``
# and ``automation/apps._APP_ALIASES`` (PART 14).  Deliberately the same
# names the parser resolves, so a corroborated command is guaranteed to be
# actionable downstream.
_KNOWN_APP_ALIASES: frozenset[str] = frozenset({
    "chrome", "google chrome", "chrome browser", "browser", "my browser",
    "calculator", "calc", "windows calculator",
    "notepad", "paint", "mspaint",
    "edge", "microsoft edge", "ms edge",
    "explorer", "file explorer",
    "vscode", "vs code", "code", "visual studio code", "code editor",
    "cmd", "command prompt", "cmd prompt",
    "powershell", "terminal",
    "settings", "control panel",
    "word", "excel", "powerpoint",
    "spotify", "itunes", "vlc", "firefox",
    "camera", "mail", "photos",
    "discord", "slack", "zoom", "youtube",
})

# Canonical whole-command forms that must survive a low-confidence short
# transcript (media control, volume, confirmations, common aliases).
_KNOWN_COMMANDS: frozenset[str] = frozenset({
    "play music", "play a song", "play the song", "play songs",
    "play track", "start music", "start playing music", "start the music",
    "put on music", "put on a song", "music please",
    "pause music", "pause the music", "stop music", "resume music",
    "pause", "stop", "resume", "play",
    "next track", "previous track", "next", "previous",
    "increase volume", "decrease volume", "volume up", "volume down",
    "turn up the volume", "turn down the volume", "lower the volume",
    "mute volume", "unmute volume", "mute", "unmute",
    "take a screenshot", "screenshot",
    "what time is it", "whats the time", "current time",
    "yes", "yeah", "yep", "sure", "ok", "okay", "correct",
    "no", "nope", "cancel", "stop that", "never mind",
})

# Verb prefixes that mark a deterministic app/action command.  Longest
# alternatives first so the regex prefers "switch to" over "switch".
_VERB_PATTERN = re.compile(
    r"^(?P<verb>open\s+up|switch\s+to|look\s+up|search\s+for|bring\s+to\s+front|"
    r"open|launch|start|run|close|quit|exit|stop|terminate|kill|focus|"
    r"minimize|maximize|restore|search|find|google|play|pause|resume|mute|"
    r"unmute|increase|decrease|lower|raise)\s+(?P<rest>.+?)\s*$",
    re.IGNORECASE,
)

# Filler words stripped from the app token before alias matching.
_FILLERS: frozenset[str] = frozenset({
    "the", "a", "an", "please", "some", "my", "app", "for", "me", "up",
})


def _words(text: str) -> list[str]:
    """Tokenise free text into lowercase alphanumeric words."""
    return re.findall(r"[a-z0-9]+", (text or "").casefold())


def _normalize(text: str) -> str:
    return " ".join(_words(text))


def _strip_fillers(text: str) -> str:
    if not text:
        return ""
    tokens = [
        token for token in text.split() if token.casefold() not in _FILLERS
    ]
    return " ".join(tokens).strip()


def repetition_score(text: str) -> float:
    """Fraction of words that belong to a repeated run of the same
    word / bigram / trigram (the decoder-loop shape).

    Returns 0.0 for anything short (< 4 words) or non-repetitive.
    """
    words = _words(text)
    n = len(words)
    if n < 4:
        return 0.0
    best = 1  # most words covered by one repeated unit (count * unit_len)
    for unit_len in (1, 2, 3):
        counts: dict[tuple[str, ...], int] = {}
        for i in range(n - unit_len + 1):
            unit = tuple(words[i:i + unit_len])
            counts[unit] = counts.get(unit, 0) + 1
        for count in counts.values():
            if count >= 3:
                best = max(best, count * unit_len)
    if best < 4:
        return 0.0
    return best / n


def is_pathological(text: str) -> bool:
    """True when *text* has the pathological-repetition shape Whisper
    produces when it runs away on noise/silence (PART 5/6)."""
    score = repetition_score(text)
    return score >= 0.5


def known_app_command(text: str) -> bool:
    """True when *text* looks like a deterministic command the parser can
    act on: a known canonical command, a verb + known app, or a bare known
    app word (PART 1/2/14)."""
    if not text or not text.strip():
        return False
    norm = _normalize(text)
    if norm in _KNOWN_COMMANDS:
        return True
    match = _VERB_PATTERN.match(norm)
    if match:
        rest = _strip_fillers(match.group("rest"))
        if rest and rest in _KNOWN_APP_ALIASES:
            return True
    return norm in _KNOWN_APP_ALIASES


def plausible_command(text: str) -> bool:
    """Conservative corroboration: a clean, non-pathological known command."""
    if is_pathological(text):
        return False
    return known_app_command(text)


# Filler tokens Whisper commonly appends/prepends around an otherwise complete
# short command ("Please open, calculator. done." -> "open calculator").
# Only stripped from the leading/trailing edges, and only when the remainder
# is still clearly a command — genuine user speech is never silently modified.
_COMMAND_FILLERS: frozenset[str] = frozenset({
    "please", "done", "okay", "ok", "thanks", "thank", "sir", "hey", "hi",
})


def normalize_command_text(text: str) -> str:
    """Strip leading/trailing STT filler around a complete short command.

    Returns the normalized command when the remainder is clearly a command
    (2+ words, or a single known-command word); otherwise returns the input
    unchanged so genuine speech is preserved.

    Examples::

        "Please open, calculator. done." -> "open calculator"
        "open chrome."                   -> "open chrome"
        "play music."                    -> "play music"
    """
    if not text or not text.strip():
        return text or ""
    tokens = _words(text)
    if not tokens:
        return text.strip()
    start, end = 0, len(tokens)
    while start < end and tokens[start] in _COMMAND_FILLERS:
        start += 1
    while end > start and tokens[end - 1] in _COMMAND_FILLERS:
        end -= 1
    remainder = tokens[start:end]
    if not remainder:
        return text.strip()
    norm = " ".join(remainder)
    if len(remainder) >= 2 or known_app_command(norm):
        return norm
    return text.strip()
