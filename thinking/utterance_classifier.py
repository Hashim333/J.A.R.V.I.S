"""
thinking/utterance_classifier.py

The classification gate at the top of the JARVIS pipeline.

Every user utterance is first classified into exactly one
``UtteranceCategory``. Only categories that describe an action the
computer can perform (SYSTEM_COMMAND, APPLICATION_CONTROL,
BROWSER_CONTROL, FILE_CONTROL, MEDIA_CONTROL) continue on to the
Planner/Executor. CHAT and QUESTION are answered directly by the LLM —
general conversation must never reach the executor.

Classification strategy (fast-path → LLM → fallback):

1. **Rule fast-path** — the deterministic rule-based Parser recognises
   unambiguous action commands ("open chrome", "increase volume", ...).
   These are classified without an LLM call so every-day commands stay
   instant and work even when Ollama is unreachable.
2. **LLM** — everything else (chat, questions, confirmations, unusual
   phrasings) is sent to the local LLM, which returns both a category
   and, for non-action categories, a natural response.
3. **Fallback** — if the LLM cannot be reached, lightweight heuristics
   provide a sensible category and a canned response so the assistant
   degrades gracefully instead of crashing or mis-routing to the executor.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from enum import Enum

from brain.llm import LLM
from brain.parser import Parser

logger = logging.getLogger(__name__)


class UtteranceCategory(str, Enum):
    """Every possible classification for a user utterance."""

    CHAT = "CHAT"
    QUESTION = "QUESTION"
    SYSTEM_COMMAND = "SYSTEM_COMMAND"
    APPLICATION_CONTROL = "APPLICATION_CONTROL"
    BROWSER_CONTROL = "BROWSER_CONTROL"
    FILE_CONTROL = "FILE_CONTROL"
    MEDIA_CONTROL = "MEDIA_CONTROL"
    CONFIRMATION = "CONFIRMATION"
    CANCELLATION = "CANCELLATION"


# Categories that must NEVER reach the executor.
NON_ACTION_CATEGORIES: frozenset[UtteranceCategory] = frozenset({
    UtteranceCategory.CHAT,
    UtteranceCategory.QUESTION,
    UtteranceCategory.CONFIRMATION,
    UtteranceCategory.CANCELLATION,
})

# Categories that describe an action and continue to Planner/Executor.
ACTION_CATEGORIES: frozenset[UtteranceCategory] = frozenset({
    UtteranceCategory.SYSTEM_COMMAND,
    UtteranceCategory.APPLICATION_CONTROL,
    UtteranceCategory.BROWSER_CONTROL,
    UtteranceCategory.FILE_CONTROL,
    UtteranceCategory.MEDIA_CONTROL,
})


@dataclass(frozen=True)
class ClassificationResult:
    """The outcome of classifying a single utterance."""

    category: UtteranceCategory
    response: str = ""
    source: str = "llm"
    data: dict[str, object] = field(default_factory=dict)


# ── Rule fast-path: Parser intent → category ──────────────────────────────

_INTENT_TO_CATEGORY: dict[str, UtteranceCategory] = {
    # Applications
    "open_app": UtteranceCategory.APPLICATION_CONTROL,
    "close_app": UtteranceCategory.APPLICATION_CONTROL,
    "focus_app": UtteranceCategory.APPLICATION_CONTROL,
    "restart_app": UtteranceCategory.APPLICATION_CONTROL,
    "minimize_app": UtteranceCategory.APPLICATION_CONTROL,
    "maximize_app": UtteranceCategory.APPLICATION_CONTROL,
    "restore_app": UtteranceCategory.APPLICATION_CONTROL,
    "close_all_apps": UtteranceCategory.APPLICATION_CONTROL,
    "is_running": UtteranceCategory.APPLICATION_CONTROL,
    # Browser
    "open_website": UtteranceCategory.BROWSER_CONTROL,
    "search": UtteranceCategory.BROWSER_CONTROL,
    "navigate": UtteranceCategory.BROWSER_CONTROL,
    "browser_search": UtteranceCategory.BROWSER_CONTROL,
    # Files
    "open_file": UtteranceCategory.FILE_CONTROL,
    "find_file": UtteranceCategory.FILE_CONTROL,
    "open_file_location": UtteranceCategory.FILE_CONTROL,
    "copy_file": UtteranceCategory.FILE_CONTROL,
    "move_file": UtteranceCategory.FILE_CONTROL,
    "rename_file": UtteranceCategory.FILE_CONTROL,
    "delete_file": UtteranceCategory.FILE_CONTROL,
    # Media
    "play_music": UtteranceCategory.MEDIA_CONTROL,
    # System
    "open_settings": UtteranceCategory.SYSTEM_COMMAND,
    "open_special_folder": UtteranceCategory.SYSTEM_COMMAND,
    "increase_volume": UtteranceCategory.SYSTEM_COMMAND,
    "decrease_volume": UtteranceCategory.SYSTEM_COMMAND,
    "set_volume": UtteranceCategory.SYSTEM_COMMAND,
    "mute_volume": UtteranceCategory.SYSTEM_COMMAND,
    "unmute_volume": UtteranceCategory.SYSTEM_COMMAND,
    "screenshot": UtteranceCategory.SYSTEM_COMMAND,
    "lock": UtteranceCategory.SYSTEM_COMMAND,
    "shutdown_windows": UtteranceCategory.SYSTEM_COMMAND,
    "restart": UtteranceCategory.SYSTEM_COMMAND,
    "sleep": UtteranceCategory.SYSTEM_COMMAND,
    "sign_out": UtteranceCategory.SYSTEM_COMMAND,
    "cancel_shutdown": UtteranceCategory.SYSTEM_COMMAND,
    "system_status": UtteranceCategory.SYSTEM_COMMAND,
    "set_brightness": UtteranceCategory.SYSTEM_COMMAND,
    "wifi_on": UtteranceCategory.SYSTEM_COMMAND,
    "wifi_off": UtteranceCategory.SYSTEM_COMMAND,
    "bluetooth_on": UtteranceCategory.SYSTEM_COMMAND,
    "bluetooth_off": UtteranceCategory.SYSTEM_COMMAND,
    "airplane_mode_on": UtteranceCategory.SYSTEM_COMMAND,
    "airplane_mode_off": UtteranceCategory.SYSTEM_COMMAND,
    "open_task_manager": UtteranceCategory.SYSTEM_COMMAND,
    "open_device_manager": UtteranceCategory.SYSTEM_COMMAND,
    "open_control_panel": UtteranceCategory.SYSTEM_COMMAND,
    "format_drive": UtteranceCategory.SYSTEM_COMMAND,
    "kill_process": UtteranceCategory.SYSTEM_COMMAND,
    # Vision / screen understanding
    "read_screen": UtteranceCategory.SYSTEM_COMMAND,
    "describe_screen": UtteranceCategory.SYSTEM_COMMAND,
    "click_element": UtteranceCategory.SYSTEM_COMMAND,
    "find_element": UtteranceCategory.SYSTEM_COMMAND,
    "read_pdf": UtteranceCategory.SYSTEM_COMMAND,
    "ocr_image": UtteranceCategory.SYSTEM_COMMAND,
    "read_error": UtteranceCategory.SYSTEM_COMMAND,
    "fill_form": UtteranceCategory.SYSTEM_COMMAND,
    # Security / pentest tooling
    "create_pentest_report": UtteranceCategory.SYSTEM_COMMAND,
    "organize_scan_results": UtteranceCategory.SYSTEM_COMMAND,
    "summarize_scan_results": UtteranceCategory.SYSTEM_COMMAND,
    "create_pentest_project": UtteranceCategory.SYSTEM_COMMAND,
}

# ── LLM prompt ─────────────────────────────────────────────────────────────

_CLASSIFIER_PROMPT = """You are JARVIS, a desktop assistant that controls a Windows computer. Classify the user's request into EXACTLY ONE of these categories:

CHAT - casual conversation, greetings, small talk, identity
QUESTION - a request for information or an explanation
SYSTEM_COMMAND - control the computer itself: volume, brightness, wifi, bluetooth, shutdown, restart, lock, sleep, screenshot, battery/CPU status, settings, task manager
APPLICATION_CONTROL - open, close, focus, minimize or maximize an application
BROWSER_CONTROL - open a website, navigate, web search, manage browser tabs
FILE_CONTROL - open, find, copy, move, rename or delete a file or folder
MEDIA_CONTROL - play, pause, stop or control music or video
CONFIRMATION - the user says yes, ok, sure, confirm, go ahead, do it
CANCELLATION - the user says no, cancel, stop, never mind, forget it

If the category is CHAT, QUESTION, CONFIRMATION or CANCELLATION, answer naturally as JARVIS in one or two short sentences.
For any other category, write an empty RESPONSE.

Respond EXACTLY in this format and nothing else:

CLASSIFICATION: <ONE_CATEGORY>
RESPONSE: <answer or empty>

User request: {text}"""


# ── LLM safety guard ───────────────────────────────────────────────────────
#
# A small LLM (e.g. qwen2.5:3b) occasionally labels a question like
# "what time is it" as SYSTEM_COMMAND. The executor must NEVER run on
# conversational text, so an ACTION category returned by the LLM is only
# trusted when the utterance shows some evidence of a real command.
# Otherwise the classification is downgraded to a safe QUESTION.

_ACTION_EVIDENCE_PATTERN = re.compile(
    r"\b("
    r"open|close|launch|start|stop|kill|run|quit|exit|"
    r"search|navigate|go to|visit|browse|switch tab|new tab|"
    r"play|pause|resume|skip|next|previous|repeat|stop music|"
    r"volume|mute|unmute|brightness|wifi|wi-fi|bluetooth|airplane|"
    r"shutdown|shut down|turn (off|on|up|down)|restart|reboot|sleep|lock|screenshot|sign out|log off|"
    r"file|folder|rename|delete|copy|move|create|open location|"
    r"minimize|maximize|restore|focus|show desktop|task manager|"
    r"device manager|control panel|settings|battery|status|"
    r"download|upload|zoom in|zoom out|read (screen|pdf|error|image)|"
    r"click|type|fill|find element|describe screen"
    r")\b",
    re.IGNORECASE,
)

# ── Fallback heuristics (LLM unreachable) ──────────────────────────────────

_CHAT_PATTERNS: list[tuple[re.Pattern[str], UtteranceCategory, str]] = [
    (re.compile(r"^(hello|hi|hey|yo|good (morning|afternoon|evening))\b", re.IGNORECASE),
     UtteranceCategory.CHAT, "Hello! How can I help you?"),
    (re.compile(r"(who|what) (are|is) you\b", re.IGNORECASE),
     UtteranceCategory.QUESTION, "I'm JARVIS, your desktop voice assistant."),
    (re.compile(r"how are you\b|how's it going|how are things", re.IGNORECASE),
     UtteranceCategory.CHAT, "I'm doing well, thanks for asking!"),
    (re.compile(r"can you hear me|are you (there|listening)|are you alive", re.IGNORECASE),
     UtteranceCategory.QUESTION, "Yes, I can hear you loud and clear."),
    (re.compile(r"what can you do|what do you do|capabilities|help me", re.IGNORECASE),
     UtteranceCategory.QUESTION, "I can open and close apps, search the web, control browser tabs, manage files, and control system settings like volume, brightness, and Wi-Fi. What would you like me to do?"),
    (re.compile(r"(thank you|thanks)\b", re.IGNORECASE),
     UtteranceCategory.CHAT, "You're welcome!"),
    (re.compile(r"^(what|why|how|where|when|which|who|is it|are you|do you|does|can i|is there)", re.IGNORECASE),
     UtteranceCategory.QUESTION, "I couldn't reach my language model, so I can only help with commands right now. "
                                "You can ask me to open apps, search the web, or control system settings."),
]


class UtteranceClassifier:
    """Classifies user utterances into action vs. non-action categories."""

    def __init__(self, llm: LLM | None = None, parser: Parser | None = None) -> None:
        self._llm = llm or LLM()
        self._parser = parser or Parser()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def classify(self, text: str) -> ClassificationResult:
        """Classify *text* into a single ``UtteranceCategory``.

        Returns a result whose ``category`` is never ``None``. Action
        categories carry an empty ``response``; non-action categories
        carry a natural spoken/printed response.
        """
        if not text or not text.strip():
            return ClassificationResult(
                category=UtteranceCategory.CHAT,
                response="I didn't catch that. Could you say it again?",
                source="rules",
            )

        # 1. Deterministic fast-path for known action commands.
        fast = self._classify_by_rules(text)
        if fast is not None:
            logger.debug("UtteranceClassifier: rules -> %s (%r)", fast.category.value, text)
            return fast

        # 2. Deterministic canned responses (confirm/decline, greetings,
        #    "can you hear me", ...). Precise and instant — no LLM latency.
        canned = self._classify_by_canned(text)
        if canned is not None:
            return canned

        # 3. LLM classification + response (with action-evidence guard).
        return self._classify_by_llm(text)

    # ------------------------------------------------------------------
    # Rule fast-path
    # ------------------------------------------------------------------

    def _classify_by_rules(self, text: str) -> ClassificationResult | None:
        try:
            parsed = self._parser.parse(text)
        except Exception as exc:
            logger.warning("UtteranceClassifier: parser failed: %s", exc)
            return None

        if parsed is None or parsed.intent == "unknown":
            return None

        category = _INTENT_TO_CATEGORY.get(parsed.intent)
        if category is None:
            return None

        return ClassificationResult(
            category=category,
            response="",
            source="rules",
            data={"intent": parsed.intent},
        )

    # ------------------------------------------------------------------
    # LLM classification
    # ------------------------------------------------------------------

    def _classify_by_llm(self, text: str) -> ClassificationResult:
        prompt = _CLASSIFIER_PROMPT.format(text=text.strip())
        try:
            raw = self._llm.ask(prompt)
        except Exception as exc:
            logger.warning("UtteranceClassifier: LLM unavailable (%s) — using fallback", exc)
            return self._classify_by_fallback(text)

        result = self._parse_llm_response(raw)
        if result is None:
            logger.warning("UtteranceClassifier: unparseable LLM output — using fallback")
            return self._classify_by_fallback(text)

        # Safety guard: only route to the executor when the utterance
        # actually looks like a command. Prevents a misbehaving LLM from
        # sending pure conversation (e.g. "what time is it") to the executor.
        if result.category in ACTION_CATEGORIES and not self._has_action_evidence(text):
            logger.warning(
                "UtteranceClassifier: LLM said %s but no action evidence in %r — downgraded to QUESTION",
                result.category.value, text,
            )
            return ClassificationResult(
                category=UtteranceCategory.QUESTION,
                response=result.response or "I understood that as a question. What would you like me to do?",
                source="llm+guard",
            )

        logger.debug("UtteranceClassifier: llm -> %s (%r)", result.category.value, text)
        return result

    def _has_action_evidence(self, text: str) -> bool:
        """True when the text looks like a real command (parser intent or an
        action keyword). Used to keep conversational text away from the
        executor even when the LLM mislabels it."""
        try:
            parsed = self._parser.parse(text)
            if parsed is not None and parsed.intent != "unknown":
                return True
        except Exception:
            pass
        return bool(_ACTION_EVIDENCE_PATTERN.search(text))

    @staticmethod
    def _parse_llm_response(raw: str) -> ClassificationResult | None:
        """Extract CLASSIFICATION/RESPONSE from the LLM's output."""
        classification_match = re.search(
            r"CLASSIFICATION\s*:\s*([A-Z_]+)", raw, re.IGNORECASE
        )
        if not classification_match:
            return None

        raw_category = classification_match.group(1).strip().upper()
        try:
            category = UtteranceCategory(raw_category)
        except ValueError:
            logger.warning("UtteranceClassifier: unknown category %r", raw_category)
            return None

        response = ""
        response_match = re.search(
            r"RESPONSE\s*:\s*(.*?)(?:\nCLASSIFICATION|$)", raw, re.IGNORECASE | re.DOTALL
        )
        if response_match:
            response = response_match.group(1).strip()
        # The RESPONSE line runs to the end of the output; keep only lines
        # after "RESPONSE:" if the model echoed nothing else.
        if not response:
            after = re.split(r"RESPONSE\s*:\s*", raw, maxsplit=1, flags=re.IGNORECASE)
            if len(after) == 2:
                response = after[1].strip()

        return ClassificationResult(category=category, response=response, source="llm")

    # ------------------------------------------------------------------
    # Fallback heuristics
    # ------------------------------------------------------------------

    def _classify_by_fallback(self, text: str) -> ClassificationResult:
        """Used when the LLM is unreachable — degrades to canned rules only."""
        canned = self._classify_by_canned(text)
        if canned is not None:
            return canned

        lowered = text.strip().casefold()
        if lowered.endswith("?"):
            return ClassificationResult(
                category=UtteranceCategory.QUESTION,
                response="I couldn't reach my language model, so I can only help with commands right now. "
                         "You can ask me to open apps, search the web, or control system settings.",
                source="rules",
            )

        return ClassificationResult(
            category=UtteranceCategory.CHAT,
            response="I'm here. I can open and close apps, search the web, manage files, "
                     "and control system settings. What would you like me to do?",
            source="rules",
        )

    @staticmethod
    def _classify_by_canned(text: str) -> ClassificationResult | None:
        """Deterministic confirm/decline + known small-talk patterns. Returns
        ``None`` when nothing matches, so the caller falls through."""
        from brain.intent_normalizer import Intent, normalize as normalize_intent

        intent = normalize_intent(text)
        if intent in (Intent.CONFIRM, Intent.DECLINE):
            if intent is Intent.CONFIRM:
                return ClassificationResult(
                    category=UtteranceCategory.CONFIRMATION,
                    response="Got it.",
                    source="rules",
                )
            return ClassificationResult(
                category=UtteranceCategory.CANCELLATION,
                response="Cancelled.",
                source="rules",
            )

        lowered = text.strip().casefold()
        if re.search(r"^(no|nope|nah)\s*(thanks|thank you)\b", lowered):
            return ClassificationResult(
                category=UtteranceCategory.CANCELLATION,
                response="Okay, never mind.",
                source="rules",
            )
        for pattern, category, reply in _CHAT_PATTERNS:
            if pattern.search(lowered):
                return ClassificationResult(
                    category=category, response=reply, source="rules"
                )
        return None
