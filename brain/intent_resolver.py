"""
brain/intent_resolver.py

Intent resolution layer used before parsing. It performs fuzzy and phonetic
matching, supports alias lookups, and generates clarification prompts when a
low-confidence correction is detected.
"""

from __future__ import annotations

import difflib
import re
from dataclasses import dataclass, field
from memory import memory_store
from typing import Iterable


@dataclass(frozen=True)
class IntentResolutionResult:
    original_text: str
    corrected_text: str | None = None
    confidence: float = 1.0
    requires_confirmation: bool = False
    suggestions: list[str] = field(default_factory=list)


class IntentResolver:
    """Resolve likely intents before they are parsed."""

    _KNOWN_TERMS: list[str] = [
        "chrome",
        "edge",
        "firefox",
        "default browser",
        "system browser",
        "google",
        "youtube",
        "chatgpt",
        "github",
        "gmail",
        "stack overflow",
        "stackoverflow",
        "reddit",
        "linkedin",
        "whatsapp web",
        "google maps",
        "open",
        "search",
        "go to",
        "navigate",
        "close",
        "new tab",
        "new window",
        "incognito",
        "profile",
        "tab",
    ]

    _ALIASES: dict[str, str] = {
        "git hub": "github",
        "git hab": "github",
        "you tube": "youtube",
        "yu tub": "youtube",
        "yt": "youtube",
        "crome": "chrome",
        "crom": "chrome",
        "chrme": "chrome",
        "chorme": "chrome",
        "fire fox": "firefox",
        "ms edge": "edge",
        "microsoft edge": "edge",
        "default": "default browser",
        "system default": "default browser",
        "whatsapp": "whatsapp web",
        "whatapp": "whatsapp web",
        "gogle": "google",
        "gogle maps": "google maps",
        "land": "linkedin",
    }

    _AUTO_CONFIRM_THRESHOLD = 0.92
    _ASK_THRESHOLD = 0.75

    def __init__(self) -> None:
        self._learned_corrections: dict[str, str] = {}

    def suggest(self, text: str) -> IntentResolutionResult:
        if text is None:
            text = ""

        normalized = self._normalize_text(text)
        if not normalized:
            return IntentResolutionResult(original_text=text)

        if normalized in self._learned_corrections:
            corrected = self._learned_corrections[normalized]
            return IntentResolutionResult(
                original_text=text,
                corrected_text=corrected,
                confidence=1.0,
                requires_confirmation=False,
            )

        stored_correction = memory_store._data["intent_corrections"].get(normalized)
        if stored_correction:
            return IntentResolutionResult(
                original_text=text,
                corrected_text=stored_correction,
                confidence=1.0,
                requires_confirmation=False,
            )

        alias_correction = self._ALIASES.get(normalized)
        if alias_correction:
            return IntentResolutionResult(
                original_text=text,
                corrected_text=self._restore_case(text, alias_correction),
                confidence=1.0,
                requires_confirmation=False,
            )

        tokens = normalized.split()
        if not tokens:
            return IntentResolutionResult(original_text=text)

        best_corrections = self._find_corrections(tokens)
        if not best_corrections:
            return IntentResolutionResult(original_text=text)

        corrected_text = self._apply_corrections(normalized, best_corrections)
        confidence = self._average_confidence(best_corrections)
        suggestions = [correction.replacement for correction in best_corrections]

        if confidence >= self._AUTO_CONFIRM_THRESHOLD:
            return IntentResolutionResult(
                original_text=text,
                corrected_text=self._restore_case(text, corrected_text),
                confidence=confidence,
                requires_confirmation=False,
                suggestions=suggestions,
            )

        if confidence >= self._ASK_THRESHOLD:
            return IntentResolutionResult(
                original_text=text,
                corrected_text=self._restore_case(text, corrected_text),
                confidence=confidence,
                requires_confirmation=True,
                suggestions=suggestions,
            )

        fallback = self._best_matches(normalized)
        return IntentResolutionResult(
            original_text=text,
            corrected_text=None,
            confidence=confidence,
            requires_confirmation=bool(fallback),
            suggestions=fallback,
        )

    def learn(self, original_text: str, corrected_text: str) -> None:
        normalized = self._normalize_text(original_text)
        if normalized:
            self._learned_corrections[normalized] = corrected_text
            memory_store.learn_corrections([(original_text, corrected_text)])

    def _find_corrections(self, tokens: list[str]) -> list["_Correction"]:
        corrections: list[_Correction] = []
        skip_until = -1

        for index in range(len(tokens)):
            if index <= skip_until:
                continue

            best_phrase = None
            best_match = None
            for length in range(1, min(3, len(tokens) - index) + 1):
                phrase = " ".join(tokens[index : index + length])
                candidate = self._best_match_for_phrase(phrase)
                if candidate and (best_match is None or candidate.score > best_match.score):
                    best_phrase = phrase
                    best_match = candidate

            if best_match is None or best_match.score < self._ASK_THRESHOLD:
                continue

            replacement = self._ALIASES.get(best_phrase, best_match.term)
            if replacement == best_phrase:
                continue

            corrections.append(
                _Correction(
                    start=index,
                    end=index + len(best_phrase.split()),
                    original=best_phrase,
                    replacement=replacement,
                    score=best_match.score,
                )
            )
            skip_until = index + len(best_phrase.split()) - 1

        return corrections

    def _best_match_for_phrase(self, phrase: str) -> "_Match" | None:
        phrase = phrase.strip()
        if not phrase:
            return None

        all_terms = list(self._KNOWN_TERMS) + list(self._ALIASES.keys())
        best_match: "_Match" | None = None
        for term in all_terms:
            score = self._term_similarity(phrase, term)
            if best_match is None or score > best_match.score:
                best_match = _Match(term=term, score=score)
        return best_match

    def _term_similarity(self, phrase: str, term: str) -> float:
        ratio = difflib.SequenceMatcher(None, phrase, term).ratio()
        phonetic_bonus = 0.0
        if self._phonetic_key(phrase) == self._phonetic_key(term):
            phonetic_bonus = 0.15
        return min(1.0, ratio + phonetic_bonus)

    def _apply_corrections(self, normalized: str, corrections: list["_Correction"]) -> str:
        if not corrections:
            return normalized

        tokens = normalized.split()
        result_tokens: list[str] = []
        index = 0
        for correction in corrections:
            while index < correction.start:
                result_tokens.append(tokens[index])
                index += 1
            result_tokens.extend(correction.replacement.split())
            index = correction.end
        while index < len(tokens):
            result_tokens.append(tokens[index])
            index += 1
        return " ".join(result_tokens)

    def _average_confidence(self, corrections: list["_Correction"]) -> float:
        if not corrections:
            return 1.0
        return sum(c.score for c in corrections) / len(corrections)

    def _best_matches(self, normalized: str) -> list[str]:
        candidates = difflib.get_close_matches(
            normalized,
            list(self._KNOWN_TERMS) + list(self._ALIASES.keys()),
            n=3,
            cutoff=0.6,
        )
        return [self._ALIASES.get(candidate, candidate) for candidate in candidates]

    @staticmethod
    def _restore_case(original: str, corrected: str) -> str:
        if original.isupper():
            return corrected.upper()
        if original.istitle():
            return corrected.title()
        return corrected

    @staticmethod
    def _normalize_text(text: str) -> str:
        text = text.casefold().strip()
        text = re.sub(r"[^\w\s]+", " ", text)
        return " ".join(text.split())

    @staticmethod
    def _phonetic_key(text: str) -> str:
        text = re.sub(r"[^a-z]", "", text.lower())
        if not text:
            return ""
        mapping = {
            "b": "1",
            "f": "1",
            "p": "1",
            "v": "1",
            "c": "2",
            "g": "2",
            "j": "2",
            "k": "2",
            "q": "2",
            "s": "2",
            "x": "2",
            "z": "2",
            "d": "3",
            "t": "3",
            "l": "4",
            "m": "5",
            "n": "5",
            "r": "6",
        }
        key = [text[0]]
        last = mapping.get(text[0], "")
        for char in text[1:]:
            code = mapping.get(char, "")
            if code and code != last:
                key.append(code)
            last = code
        return "".join(key)


@dataclass(frozen=True)
class _Match:
    term: str
    score: float


@dataclass(frozen=True)
class _Correction:
    start: int
    end: int
    original: str
    replacement: str
    score: float
