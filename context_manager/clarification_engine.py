from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Any

logger = logging.getLogger(__name__)


class ClarificationState(Enum):
    NONE = auto()
    AWAITING_ANSWER = auto()


class ClarificationType(Enum):
    APP_ALREADY_RUNNING = auto()
    TAB_ALREADY_OPEN = auto()
    SWITCH_OR_NEW = auto()
    CURRENT_OR_NEW_TAB = auto()
    WHICH_BROWSER = auto()
    MEDIA_PLAYING = auto()
    SEARCH_ALREADY_OPEN = auto()
    SEARCH_DESTINATION = auto()
    MUSIC_PLAYING_CONSUMER = auto()


@dataclass
class PendingClarification:
    question: str
    clarification_type: ClarificationType
    context: dict[str, Any] = field(default_factory=dict)
    follow_up_intent: str = ""


_YES_WORDS = frozenset({
    "yes", "yep", "yeah", "sure", "ok", "okay", "alright",
    "go ahead", "do it", "confirm",
})

_SWITCH_WORDS = frozenset({
    "switch", "switch to it", "existing", "that one",
    "focus it", "bring it here", "use that", "focus",
    "bring forward", "activate",
})

_CURRENT_TAB_WORDS = frozenset({
    "current", "current tab", "this tab", "this one", "here",
    "continue", "stay",
})

_NEW_WORDS = frozenset({
    "new", "another", "open another", "new one",
})

_NEW_TAB_WORDS = frozenset({
    "new tab", "another tab", "open new tab", "fresh tab",
})

_NEW_WINDOW_WORDS = frozenset({
    "new window", "another window", "open new window",
    "new instance", "separate window",
})

_NEW_PROFILE_WORDS = frozenset({
    "new profile", "another profile", "different profile",
    "different account", "another account",
})

_NO_WORDS = frozenset({
    "no", "nope", "nah", "negative",
})

_REPLACE_WORDS = frozenset({
    "replace", "replace it", "overwrite", "use this tab", "same tab",
    "here", "this one", "current",
})

_KEEP_WORDS = frozenset({
    "keep", "keep it", "keep playing", "stay", "continue",
    "leave it", "dont change",
})

_QUEUE_WORDS = frozenset({
    "queue", "queue it", "add to queue", "add", "play next",
})

_SEARCH_HERE_WORDS = frozenset({
    "search here", "on youtube", "on this site", "use current",
    "here", "this site", "current page",
})

_SEARCH_THERE_WORDS = frozenset({
    "search there", "on google", "other site", "other",
    "google it", "use google",
})

_ANOTHER_BROWSER_WORDS = frozenset({
    "another browser", "different browser", "other browser",
})

_CANCEL_WORDS = frozenset({
    "cancel", "cancel it", "never mind", "forget it", "skip",
    "abort", "leave it", "leave it be",
})

# Expected answers per clarification type, with canonical labels and the
# natural-language synonyms that map to them (milestone Task 2). Each entry:
#   (canonical_label, action, synonyms)
_EXPECTED_ANSWERS: dict[ClarificationType, list[tuple[str, str, frozenset[str]]]] = {
    ClarificationType.APP_ALREADY_RUNNING: [
        ("existing", "switch_to_existing", frozenset({
            "existing", "use this one", "current", "current window",
            "switch", "switch to it", "that one", "focus it",
            "bring it here", "use that", "focus", "bring forward",
            "activate", "yes",
        })),
        ("new window", "open_new_window", frozenset({
            "new window", "another window", "open new window",
            "new instance", "separate window", "fresh window",
            "open another", "new", "another", "yes",
        })),
        ("new tab", "open_new_tab", frozenset({
            "new tab", "another tab", "open new tab", "fresh tab",
        })),
        ("different profile", "open_new_profile", frozenset({
            "different profile", "new profile", "another profile",
            "different account", "another account",
        })),
        ("cancel", "cancel", _CANCEL_WORDS),
    ],
    ClarificationType.TAB_ALREADY_OPEN: [
        ("switch to it", "switch_to_tab", frozenset({
            "switch", "switch to it", "existing", "that one",
            "focus it", "bring it here", "use that", "focus",
            "bring forward", "activate", "current", "current tab",
            "this tab", "this one", "here", "continue", "stay", "yes",
        })),
        ("new tab", "open_new_tab", frozenset({
            "new tab", "another tab", "open new tab", "fresh tab",
            "new", "another", "open another", "new one",
        })),
        ("new window", "open_new_window", frozenset({
            "new window", "another window", "open new window",
            "new instance", "separate window",
        })),
        ("cancel", "cancel", _CANCEL_WORDS),
    ],
    ClarificationType.SWITCH_OR_NEW: [
        ("existing", "switch_to_existing", frozenset({
            "switch", "switch to it", "existing", "that one",
            "focus it", "bring it here", "use that", "focus",
            "bring forward", "activate", "current", "current tab",
            "this tab", "this one", "here", "continue", "stay", "yes",
        })),
        ("new window", "open_new_window", frozenset({
            "new window", "another window", "open new window",
            "new instance", "separate window", "fresh window",
            "open another", "new", "another", "new one",
        })),
        ("new tab", "open_new_tab", frozenset({
            "new tab", "another tab", "open new tab", "fresh tab",
        })),
        ("cancel", "cancel", _CANCEL_WORDS),
    ],
    ClarificationType.CURRENT_OR_NEW_TAB: [
        ("current tab", "use_current_tab", frozenset({
            "current", "current tab", "this tab", "this one", "here",
            "continue", "stay", "yes",
        })),
        ("new tab", "open_new_tab", frozenset({
            "new tab", "another tab", "open new tab", "fresh tab",
            "new", "another", "open another", "new one",
        })),
        ("cancel", "cancel", _CANCEL_WORDS),
    ],
    ClarificationType.MEDIA_PLAYING: [
        ("continue", "continue_current", frozenset({
            "continue", "current", "current tab", "this tab", "this one",
            "here", "stay", "yes",
        })),
        ("new tab", "open_new_tab", frozenset({
            "new tab", "another tab", "open new tab", "fresh tab",
            "new", "another", "open another", "new one",
        })),
        ("new window", "open_new_window", frozenset({
            "new window", "another window", "open new window",
            "new instance", "separate window",
        })),
        ("cancel", "cancel", _CANCEL_WORDS),
    ],
    ClarificationType.SEARCH_ALREADY_OPEN: [
        ("replace search", "replace_search", frozenset({
            "replace", "replace it", "overwrite", "use this tab",
            "same tab", "here", "this one", "current", "yes",
        })),
        ("new tab", "open_new_tab", frozenset({
            "new tab", "another tab", "open new tab", "fresh tab",
            "new", "another", "open another", "new one",
        })),
        ("new window", "open_new_window", frozenset({
            "new window", "another window", "open new window",
            "new instance", "separate window",
        })),
        ("cancel", "cancel", _CANCEL_WORDS),
    ],
    ClarificationType.SEARCH_DESTINATION: [
        ("here", "search_here", frozenset({
            "search here", "on youtube", "on this site", "use current",
            "here", "this site", "current page", "yes", "youtube",
        })),
        ("there", "search_there", frozenset({
            "search there", "on google", "other site", "other",
            "google it", "use google", "google", "no",
        })),
        ("cancel", "cancel", _CANCEL_WORDS),
    ],
    ClarificationType.MUSIC_PLAYING_CONSUMER: [
        ("replace music", "replace_music", frozenset({
            "replace", "replace it", "overwrite", "use this tab", "same tab",
        })),
        ("keep music", "keep_music", frozenset({
            "keep", "keep it", "keep playing", "stay", "continue",
            "leave it", "dont change", "current", "current tab",
            "this tab", "this one", "here", "yes",
        })),
        ("queue music", "queue_music", frozenset({
            "queue", "queue it", "add to queue", "add", "play next",
        })),
        ("new tab", "open_new_tab", frozenset({
            "new tab", "another tab", "open new tab", "fresh tab",
            "new", "another", "open another", "new one",
        })),
        ("cancel", "cancel", _CANCEL_WORDS),
    ],
}


class ClarificationEngine:
    def __init__(self) -> None:
        self._pending: PendingClarification | None = None
        self._last_command: str = ""

    @property
    def has_pending(self) -> bool:
        return self._pending is not None

    @property
    def pending_question(self) -> str:
        return self._pending.question if self._pending else ""

    @property
    def pending_context(self) -> dict[str, Any]:
        return self._pending.context if self._pending else {}

    @property
    def pending_type(self) -> ClarificationType | None:
        return self._pending.clarification_type if self._pending else None

    def store_last_command(self, command: str) -> None:
        self._last_command = command

    def get_last_command(self) -> str:
        return self._last_command

    def set_pending(
        self,
        question: str,
        ctype: ClarificationType,
        context: dict[str, Any] | None = None,
        follow_up_intent: str = "",
    ) -> None:
        self._pending = PendingClarification(
            question=question,
            clarification_type=ctype,
            context=context or {},
            follow_up_intent=follow_up_intent,
        )

    def resolve_answer(self, answer: str) -> dict[str, Any]:
        if not self._pending:
            return {"action": "none", "intent": ""}

        pending = self._pending
        answer_lower = answer.strip().casefold()

        result: dict[str, Any] = {
            "clarification_type": pending.clarification_type,
            "context": dict(pending.context),
            "original_question": pending.question,
            "raw_answer": answer,
        }

        action = self._match_answer(answer_lower, pending.clarification_type)
        if action is None:
            action = self._match_expected_synonym(answer_lower, pending.clarification_type)
        if action is None and answer_lower in _CANCEL_WORDS:
            action = "cancel"

        if action:
            label, confidence = self._label_for_action(action, pending.clarification_type, answer_lower)
            result["action"] = action
            result["intent"] = pending.follow_up_intent
            result["matched_answer"] = label
            result["confidence"] = confidence
            result["decision"] = action
        else:
            result["action"] = "unknown"
            result["matched_answer"] = ""
            result["confidence"] = 0.0
            result["decision"] = "unknown"

        result["expected_answers"] = self.expected_answers
        self._log_resolution(result, answer)

        self.clear_pending()
        return result

    @property
    def expected_answers(self) -> list[str]:
        """Canonical labels the user is expected to choose from for the
        pending clarification (dynamic for browser/provider questions)."""
        if not self._pending:
            return []
        ctype = self._pending.clarification_type
        if ctype == ClarificationType.WHICH_BROWSER:
            browsers = self._pending.context.get("browsers", [])
            labels = [b.get("display_name") or b.get("name", "") for b in browsers]
            return labels + ["cancel"]
        if ctype == ClarificationType.SEARCH_DESTINATION:
            providers = self._pending.context.get("providers", [])
            labels = [p if p in ("youtube", "google") else p for p in providers]
            return labels + ["cancel"]
        entries = _EXPECTED_ANSWERS.get(ctype, [])
        return [label for label, _, _ in entries]

    def _label_for_action(
        self,
        action: str,
        ctype: ClarificationType,
        answer: str,
    ) -> tuple[str, float]:
        """Map a matched action back to its canonical label and a confidence
        score based on how the raw answer matched its synonyms."""
        if action == "cancel":
            return "cancel", 1.0

        for label, candidate_action, synonyms in _EXPECTED_ANSWERS.get(ctype, []):
            if candidate_action != action:
                continue
            confidence = self._score_answer(answer, label, synonyms)
            if confidence == 0.0:
                confidence = 0.7  # legacy word-set matched, so it was intended
            return label, confidence

        if action == "select_browser":
            browsers = self._pending.context.get("browsers", []) if self._pending else []
            for b in browsers:
                name = (b.get("name", "") or "").casefold()
                disp = (b.get("display_name", "") or "").casefold()
                if answer == name or answer == disp or name in answer or disp in answer:
                    return (b.get("display_name") or b.get("name", "")), 0.9
            return "browser", 0.7

        return action, 0.7

    @staticmethod
    def _score_answer(answer: str, label: str, synonyms: frozenset[str]) -> float:
        """Score an answer against a label + synonyms.

        1.0 = exact phrase match; 0.85 = full synonym contained in the
        answer; 0.7 = multi-word overlap; 0.6 = single word overlap;
        0.0 = no match.
        """
        if answer == label or answer in synonyms:
            return 1.0
        words = answer.split()
        for syn in synonyms:
            if syn in answer:
                return 0.85
            syn_words = syn.split()
            if len(syn_words) > 1 and all(w in words for w in syn_words):
                return 0.7
        joined = "".join(syn.replace(" ", "") for syn in synonyms)
        if any(w in label.split() or w in joined for w in words):
            return 0.6
        return 0.0

    def _log_resolution(self, result: dict[str, Any], raw_answer: str) -> None:
        """Structured clarification log (milestone Task 5)."""
        logger.info(
            "\n---- CLARIFICATION ----\n"
            "Question asked: %s\n"
            "Expected answers: %s\n"
            "User response: %s\n"
            "Matched answer: %s\n"
            "Confidence: %.2f\n"
            "Decision: %s",
            result.get("original_question", "-"),
            ", ".join(result.get("expected_answers", [])) or "-",
            raw_answer or "-",
            result.get("matched_answer") or "-",
            result.get("confidence", 0.0),
            result.get("decision", "unknown"),
        )

    def _match_expected_synonym(self, answer: str, ctype: ClarificationType) -> str | None:
        """Fallback matcher that resolves an answer against the synonym sets
        declared in ``_EXPECTED_ANSWERS`` (milestone Task 2). Returns the
        canonical action or ``None``."""
        for _, candidate_action, synonyms in _EXPECTED_ANSWERS.get(ctype, []):
            if answer == candidate_action or answer in synonyms:
                return candidate_action
            for syn in synonyms:
                if syn in answer or answer in syn:
                    return candidate_action
        return None

    def _match_answer(self, answer: str, ctype: ClarificationType) -> str | None:
        if ctype == ClarificationType.APP_ALREADY_RUNNING:
            return self._match_app_running(answer)
        elif ctype == ClarificationType.TAB_ALREADY_OPEN:
            return self._match_tab_open(answer)
        elif ctype == ClarificationType.SWITCH_OR_NEW:
            return self._match_switch_or_new(answer)
        elif ctype == ClarificationType.CURRENT_OR_NEW_TAB:
            return self._match_current_or_new(answer)
        elif ctype == ClarificationType.WHICH_BROWSER:
            return self._match_which_browser(answer)
        elif ctype == ClarificationType.MEDIA_PLAYING:
            return self._match_media_playing(answer)
        elif ctype == ClarificationType.SEARCH_ALREADY_OPEN:
            return self._match_search_already_open(answer)
        elif ctype == ClarificationType.SEARCH_DESTINATION:
            return self._match_search_destination(answer)
        elif ctype == ClarificationType.MUSIC_PLAYING_CONSUMER:
            return self._match_music_playing_consumer(answer)
        return None

    def _match_app_running(self, answer: str) -> str | None:
        if answer in _SWITCH_WORDS or answer in _YES_WORDS:
            return "switch_to_existing"
        if answer in _NEW_WINDOW_WORDS:
            return "open_new_window"
        if answer in _NEW_PROFILE_WORDS:
            return "open_new_profile"
        if answer in _NEW_TAB_WORDS:
            return "open_new_tab"
        if answer in _NEW_WORDS:
            return "open_new_window"
        if answer in _NO_WORDS:
            return "open_new_window"
        return None

    def _match_tab_open(self, answer: str) -> str | None:
        if answer in _SWITCH_WORDS or answer in _YES_WORDS or answer in _CURRENT_TAB_WORDS:
            return "switch_to_tab"
        if answer in _NEW_TAB_WORDS:
            return "open_new_tab"
        if answer in _NEW_WINDOW_WORDS:
            return "open_new_window"
        if answer in _NEW_WORDS:
            return "open_new_tab"
        if answer in _NO_WORDS:
            return "open_new_tab"
        return None

    def _match_switch_or_new(self, answer: str) -> str | None:
        if answer in _SWITCH_WORDS or answer in _YES_WORDS or answer in _CURRENT_TAB_WORDS:
            return "switch_to_existing"
        if answer in _NEW_WINDOW_WORDS:
            return "open_new_window"
        if answer in _NEW_TAB_WORDS:
            return "open_new_tab"
        if answer in _NEW_WORDS:
            return "open_new_window"
        if answer in _NO_WORDS:
            return "open_new_window"
        return None

    def _match_current_or_new(self, answer: str) -> str | None:
        if answer in _CURRENT_TAB_WORDS or answer in _YES_WORDS:
            return "use_current_tab"
        if answer in _NEW_TAB_WORDS:
            return "open_new_tab"
        if answer in _NEW_WINDOW_WORDS:
            return "open_new_tab"
        if answer in _NEW_WORDS:
            return "open_new_tab"
        if answer in _NO_WORDS:
            return "open_new_tab"
        return None

    def _match_which_browser(self, answer: str) -> str | None:
        browsers_in_context = self._pending.context.get("browsers", [])
        if not browsers_in_context:
            return None

        answer_lower = answer.strip().casefold()
        words_in_answer = answer_lower.split()

        for b in browsers_in_context:
            nm = b.get("name", "").casefold()
            disp = b.get("display_name", "").casefold()
            proc = b.get("process_name", "").casefold().replace(".exe", "")

            candidates = [nm, disp, proc] + disp.split()
            for candidate in candidates:
                if not candidate:
                    continue
                if candidate == answer_lower:
                    return "select_browser"
                if candidate in answer_lower:
                    return "select_browser"
                if answer_lower in candidate:
                    return "select_browser"

            for word in words_in_answer:
                if word and (word == nm or word == disp or word == proc):
                    return "select_browser"
                if word and word in disp:
                    return "select_browser"

        return None

    def _match_media_playing(self, answer: str) -> str | None:
        if answer in _CURRENT_TAB_WORDS or answer in _YES_WORDS:
            return "continue_current"
        if answer in _NEW_TAB_WORDS:
            return "open_new_tab"
        if answer in _NEW_WINDOW_WORDS:
            return "open_new_window"
        if answer in _NEW_WORDS:
            return "open_new_tab"
        if answer in _NO_WORDS:
            return "open_new_tab"
        return None

    def _match_search_already_open(self, answer: str) -> str | None:
        if answer in _REPLACE_WORDS:
            return "replace_search"
        if answer in _SWITCH_WORDS or answer in _CURRENT_TAB_WORDS:
            return "replace_search"
        if answer in _NEW_TAB_WORDS:
            return "open_new_tab"
        if answer in _NEW_WINDOW_WORDS:
            return "open_new_window"
        if answer in _NEW_WORDS:
            return "open_new_tab"
        if answer in _NO_WORDS:
            return "open_new_tab"
        return None

    def _match_search_destination(self, answer: str) -> str | None:
        if answer in _SEARCH_HERE_WORDS:
            return "search_here"
        if answer in _SEARCH_THERE_WORDS:
            return "search_there"
        provider_context = self._pending.context.get("providers", [])
        answer_lower = answer.strip().casefold()
        for p in provider_context:
            if p in answer_lower or answer_lower in p:
                if "youtube" in p or "yt" in p:
                    return "search_here"
                return "search_there"
        if answer in _YES_WORDS:
            return "search_here"
        return None

    def _match_music_playing_consumer(self, answer: str) -> str | None:
        if answer in _REPLACE_WORDS:
            return "replace_music"
        if answer in _KEEP_WORDS:
            return "keep_music"
        if answer in _QUEUE_WORDS:
            return "queue_music"
        if answer in _CURRENT_TAB_WORDS:
            return "keep_music"
        if answer in _NEW_TAB_WORDS:
            return "open_new_tab"
        if answer in _NEW_WORDS:
            return "open_new_tab"
        return None

    def clear_pending(self) -> None:
        self._pending = None

    def matches_expected(self, answer: str) -> bool:
        """Non-destructive check: would this answer resolve against the
        pending clarification? Used to detect context switches without
        clearing pending state."""
        if not self._pending:
            return False
        answer_lower = answer.strip().casefold()
        if answer_lower in _CANCEL_WORDS:
            return True
        return self._match_answer(answer_lower, self._pending.clarification_type) is not None


def _build_select_browser(b: dict) -> str | None:
    return "select_browser"


def is_media_tab(tab_title: str, tab_url: str) -> bool:
    title_lower = tab_title.casefold()
    url_lower = tab_url.casefold()
    if "youtube music" in title_lower or "youtube music" in url_lower:
        return True
    if "youtube.com/watch" in url_lower and "music" not in title_lower:
        return False
    if "spotify" in title_lower or "spotify" in url_lower:
        return True
    if "netflix" in title_lower or "netflix" in url_lower:
        return True
    if "soundcloud" in title_lower or "soundcloud" in url_lower:
        return True
    if "tidal" in title_lower or "tidal" in url_lower:
        return True
    if "pandora" in title_lower or "pandora" in url_lower:
        return True
    return False
