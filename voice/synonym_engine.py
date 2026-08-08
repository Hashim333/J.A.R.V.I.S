"""
voice/synonym_engine.py

``SynonymEngine`` — canonicalises recognised speech into the canonical phrases
the intent parser understands.

The speech recogniser returns whatever words it heard ("start music",
"music please", "play a song", "open up chrome").  Different phrasings of the
same command must collapse onto one canonical form so the parser always lands
on the same intent (e.g. ``play music`` -> ``play_music``):

    play music / play a song / start music / music please / put on music
        -> "play music"
    open up chrome / open the browser / launch the browser
        -> "open chrome" / "open browser"
    turn up the volume / increase the volume / turn the volume up
        -> "volume up"

Only *whole-utterance* rewrites are performed (exact match after light
normalisation), so a real query like "search relaxing music" is never
mangled.  ``canonicalize`` reports the applied changes so the caller can
surface both the raw and canonical text internally.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

# Filler phrases removed before matching so "music please" and "please play
# music" reach the same canonical key.  Kept deliberately small — the intent
# parser performs its own deeper filler stripping later.
_FILLERS: tuple[str, ...] = (
    "could you", "can you", "would you", "will you", "kindly",
    "please", "just", "actually", "simply", "the", "a", "an", "some",
)

#: Normalised phrase -> canonical command phrase.
#: ``_CANONICAL_MAP`` keys are matched exactly (after light normalisation and
#: filler removal), so no substring can corrupt a longer query.
_CANONICAL_MAP: dict[str, str] = {
    # ---- Media (PLAY_MEDIA) ----
    "play music": "play music",
    "play a song": "play music",
    "play the song": "play music",
    "play songs": "play music",
    "play a song": "play music",
    "play track": "play music",
    "start music": "play music",
    "start playing music": "play music",
    "start the music": "play music",
    "put on music": "play music",
    "put on a song": "play music",
    "music please": "play music",
    "play music please": "play music",
    "play something": "play music",
    "play some music": "play music",
    # ---- Browser / apps (OPEN_APP) ----
    "open chrome": "open chrome",
    "open up chrome": "open chrome",
    "open google chrome": "open chrome",
    "open the browser": "open browser",
    "open up the browser": "open browser",
    "open up browser": "open browser",
    "start the browser": "open browser",
    "launch the browser": "open browser",
    "browser please": "open browser",
    "open a browser": "open browser",
    # ---- Volume (parser verb synonyms that need "the"/"up"/"down") ----
    "turn up the volume": "volume up",
    "turn the volume up": "volume up",
    "increase the volume": "increase volume",
    "raise the volume": "increase volume",
    "volume please": "volume up",
    "turn down the volume": "decrease volume",
    "turn the volume down": "decrease volume",
    "lower the volume": "decrease volume",
    "decrease the volume": "decrease volume",
    "mute the volume": "mute volume",
    "unmute the volume": "unmute volume",
    # ---- Screenshot ----
    "screenshot please": "take a screenshot",
    "take a screenshot please": "take a screenshot",
    # ---- Wake / sleep ----
    "go back to sleep": "go to sleep",
    "go to sleep please": "go to sleep",
}

#: Identity canonical forms (a phrase mapped onto itself is a no-op) — listed
#: for the spec's canonical-intent documentation only.
#: ``play music`` / ``open chrome`` / ``open browser``


@dataclass(frozen=True)
class CanonicalResult:
    """Outcome of canonicalisation.

    ``text`` is the canonical command phrase; ``raw`` is what the recogniser
    actually returned; ``changes`` lists every ``(matched, canonical)``
    rewrite so the caller can show both internally.
    """

    raw: str
    text: str
    changes: list[tuple[str, str]] = field(default_factory=list)

    @property
    def changed(self) -> bool:
        return bool(self.changes)


class SynonymEngine:
    """Whole-utterance synonym canonicalisation (stateless)."""

    @classmethod
    def canonicalize(cls, text: str) -> CanonicalResult:
        raw = (text or "").strip()
        if not raw:
            return CanonicalResult(raw, raw)

        normalized = cls._normalize(raw)
        stripped = cls._strip_fillers(normalized)
        # Prefer the filler-stripped form, then the raw form.  A rewrite is
        # meaningful only when it actually changes what the user said.
        candidates = [stripped, normalized] if stripped != normalized else [normalized]
        for candidate in candidates:
            canonical = _CANONICAL_MAP.get(candidate)
            if canonical and canonical != normalized:
                return CanonicalResult(raw, canonical, [(candidate, canonical)])
        return CanonicalResult(raw, raw)

    @staticmethod
    def _normalize(text: str) -> str:
        text = text.casefold()
        text = re.sub(r"[^\w\s]", "", text)
        return " ".join(text.split())

    @staticmethod
    def _strip_fillers(text: str) -> str:
        pattern = r"\b(" + "|".join(
            re.escape(filler) for filler in _FILLERS
        ) + r")\b"
        stripped = re.sub(pattern, "", text, flags=re.IGNORECASE)
        return " ".join(stripped.split())
