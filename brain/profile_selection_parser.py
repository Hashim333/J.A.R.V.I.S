"""
brain/profile_selection_parser.py

Intent-based parser for selecting one item from a named list by voice or text.
Reusable anywhere in JARVIS — has no Chrome-specific logic.

Usage:
    parser = ProfileSelectionParser(
        candidates=["Muhammed", "Hashi", "amithcs.in"],
        aliases={
            "my profile": 0,
            "mine": 0,
            "default": 0,
            "gaming profile": 1,
        },
    )
    result = parser.parse("the first one")
    # result.index == 0, result.confidence == 100, result.low_confidence == False
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from difflib import get_close_matches, SequenceMatcher
from typing import Sequence

try:
    from rapidfuzz import fuzz, process as rf_process
except ImportError:  # pragma: no cover - exercised only when RapidFuzz is absent
    fuzz = None
    rf_process = None


# ---------------------------------------------------------------------------
# Public result type
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ParseResult:
    index: int          # 0-based index into candidates; -1 = no match
    name: str           # display name of the matched candidate, or ""
    confidence: float   # 0–100
    low_confidence: bool


# ---------------------------------------------------------------------------
# Normalisation helpers
# ---------------------------------------------------------------------------

# Words that carry no selection signal — stripped before matching.
_NOISE: frozenset[str] = frozenset({
    "please", "kindly", "can", "you", "could", "would", "i", "want",
    "the", "a", "an", "my", "me", "of", "open", "use",
    "load", "launch", "start", "go", "with", "just", "like", "that",
    "this", "it", "is", "am", "are", "was", "were", "be", "been",
    "do", "does", "did", "doing", "has", "have", "had", "get", "got",
    "up", "down", "in", "out", "on", "off", "over", "under",
    "also", "too", "very", "really", "actually", "basically", "literally",
    "maybe", "probably", "some", "any", "all", "every", "each", "both",
    "okay", "ok", "yeah", "yes", "no", "hey", "so", "well", "now",
    "then", "there", "here", "right", "left", "back", "front",
    "let", "lets", "make", "take", "put", "set", "need", "gotta",
    "wanna", "gonna", "try", "tryna", "tell", "show", "find", "give",
    "going", "goingto",
    # Context words spoken around a selection that carry no index signal.
    "number", "profile", "chrome", "select", "choose", "pick",
})

# Spoken-number / homophone -> digit string.
_WORD_TO_DIGIT: dict[str, str] = {
    "zero": "0", "oh": "0", "owe": "0",
    "one": "1", "won": "1", "wan": "1",
    "two": "2", "too": "2", "tu": "2", "to": "2",
    "three": "3", "free": "3", "tree": "3", "threee": "3",
    "four": "4", "fore": "4", "for": "4",
    "five": "5", "fife": "5", "fiv": "5",
    "six": "6", "sicks": "6", "sik": "6",
    "seven": "7", "sevn": "7", "seben": "7",
    "eight": "8", "ate": "8", "eit": "8",
    "nine": "9", "niner": "9", "nein": "9",
}

# Ordinal / positional words → 0-based index.
_ORDINAL_TO_INDEX: dict[str, int] = {
    "first": 0, "1st": 0,
    "second": 1, "2nd": 1,
    "third": 2, "3rd": 2,
    "fourth": 3, "4th": 3,
    "fifth": 4, "5th": 4,
    "sixth": 5, "6th": 5,
    "seventh": 6, "7th": 6,
    "eighth": 7, "8th": 7,
    "ninth": 8, "9th": 8,
}

# Confidence threshold below which the result is flagged as low-confidence.
_LOW_CONFIDENCE_THRESHOLD = 70.0

_PROFILE_NAME_ALIASES: dict[str, tuple[str, ...]] = {
    "hashi": ("aashi", "ashi"),
}


def _normalise(text: str) -> str:
    """Casefold, strip punctuation, collapse whitespace and repeated tokens."""
    # Unicode normalise then casefold
    text = unicodedata.normalize("NFKD", text).casefold()
    # Remove punctuation except hyphens (keep "amithcs.in" dot for name matching)
    text = re.sub(r"[^\w\s.\-]", " ", text)
    # Collapse whitespace
    tokens = text.split()
    # Map spoken digits / homophones token-by-token
    tokens = [_WORD_TO_DIGIT.get(t, t) for t in tokens]
    # Deduplicate consecutive identical tokens ("1 1" → ["1"])
    deduped: list[str] = []
    for tok in tokens:
        if not deduped or tok != deduped[-1]:
            deduped.append(tok)
    return " ".join(deduped)


def _strip_noise(tokens: list[str]) -> list[str]:
    return [t for t in tokens if t not in _NOISE]


def _extract_one(query: str, choices: Sequence[str]) -> tuple[str, float, int] | None:
    if not query or not choices:
        return None

    if rf_process is not None and fuzz is not None:
        match = rf_process.extractOne(
            query,
            choices,
            scorer=fuzz.WRatio,
            score_cutoff=0,
        )
        if match is None:
            return None
        matched, score, idx = match
        return str(matched), float(score), int(idx)

    close = get_close_matches(query, list(choices), n=1, cutoff=0.0)
    if not close:
        return None
    matched = close[0]
    idx = list(choices).index(matched)
    score = SequenceMatcher(None, query, matched).ratio() * 100
    return matched, score, idx


# ---------------------------------------------------------------------------
# Parser
# ---------------------------------------------------------------------------

class ProfileSelectionParser:
    """
    Parses a free-form utterance into a selection from a fixed candidate list.

    Parameters
    ----------
    candidates:
        Ordered list of display names (e.g. ["Muhammed", "Hashi", "amithcs.in"]).
    aliases:
        Optional mapping of extra phrases → 0-based index
        (e.g. {"my profile": 0, "gaming profile": 1}).
    """

    def __init__(
        self,
        candidates: Sequence[str],
        aliases: dict[str, int] | None = None,
    ) -> None:
        self._candidates = list(candidates)
        self._aliases: dict[str, int] = {}
        for phrase, idx in (aliases or {}).items():
            self._aliases[_normalise(phrase)] = idx
        # Pre-normalise candidate names for fuzzy matching
        self._norm_candidates = [_normalise(c) for c in self._candidates]
        for idx, candidate in enumerate(self._norm_candidates):
            for alias in _PROFILE_NAME_ALIASES.get(candidate, ()):
                self._aliases.setdefault(_normalise(alias), idx)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def parse(self, utterance: str) -> ParseResult:
        if not utterance or not utterance.strip():
            return self._no_match()

        normalised = _normalise(utterance)
        tokens = normalised.split()
        signal_tokens = _strip_noise(tokens)
        signal = " ".join(signal_tokens)

        if normalised in self._aliases:
            idx = self._aliases[normalised]
            return self._result(idx, 100.0)
        if signal in self._aliases:
            idx = self._aliases[signal]
            return self._result(idx, 100.0)

        for tok in signal_tokens:
            if tok in _ORDINAL_TO_INDEX:
                idx = _ORDINAL_TO_INDEX[tok]
                if idx < len(self._candidates):
                    return self._result(idx, 100.0)

        for tok in signal_tokens:
            if tok.isdigit():
                idx = int(tok) - 1
                if 0 <= idx < len(self._candidates):
                    return self._result(idx, 100.0)

        if self._candidates:
            match = _extract_one(signal, self._norm_candidates)
            if match is not None:
                _matched_str, score, idx = match
                if score >= _LOW_CONFIDENCE_THRESHOLD:
                    return self._result(idx, float(score))

            match = _extract_one(normalised, self._norm_candidates)
            if match is not None:
                _matched_str, score, idx = match
                if score >= _LOW_CONFIDENCE_THRESHOLD:
                    return self._result(idx, float(score))

            if len(signal_tokens) > 1:
                for tok in signal_tokens:
                    if len(tok) > 1:
                        match = _extract_one(tok, self._norm_candidates)
                        if match is not None:
                            _matched_str, score, idx = match
                            if score >= _LOW_CONFIDENCE_THRESHOLD:
                                return self._result(idx, float(score))

        return self._no_match()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _result(self, index: int, confidence: float) -> ParseResult:
        name = self._candidates[index] if 0 <= index < len(self._candidates) else ""
        return ParseResult(
            index=index,
            name=name,
            confidence=confidence,
            low_confidence=confidence < _LOW_CONFIDENCE_THRESHOLD,
        )

    def _no_match(self) -> ParseResult:
        return ParseResult(index=-1, name="", confidence=0.0, low_confidence=True)
