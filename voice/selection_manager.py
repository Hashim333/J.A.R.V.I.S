"""
voice/selection_manager.py

Reusable voice-based selection manager for multiple-choice scenarios.

Every module that presents multiple options to the user uses this
component instead of implementing its own prompt/retry logic.

Supports:
  - Smart parsing: "option two", "choose option 2", "pick the second one",
    "number two", "the first one", ordinals, digits, names, partial names
  - Short responses: brief summaries ("Option one: Resume.")
  - Pagination: only read first 3, support "next", "previous", "read all"
  - Cancel (say "cancel", "none", "stop")
  - Text-only fallback (when voice input is unavailable)
  - Text-to-Speech for reading options aloud
  - Context memory for follow-up selection
"""

from __future__ import annotations

import logging
import re
from typing import Callable, Sequence

logger = logging.getLogger(__name__)

_NUMBER_WORDS: dict[str, int] = {
    "one": 0, "two": 1, "three": 2, "four": 3, "five": 4,
    "six": 5, "seven": 6, "eight": 7, "nine": 8, "ten": 9,
}

_ORDINAL_WORDS: dict[str, int] = {
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

_NUMBER_NAMES: dict[int, str] = {
    1: "one", 2: "two", 3: "three", 4: "four", 5: "five",
    6: "six", 7: "seven", 8: "eight", 9: "nine", 10: "ten",
}

_CANCEL_WORDS: frozenset[str] = frozenset({
    "cancel", "c", "none", "never", "no", "exit", "stop",
    "abort", "forget", "skip", "dismiss", "go back", "back",
})

_PAGINATION_WORDS: frozenset[str] = frozenset({
    "next", "more", "next options", "show more", "continue",
    "previous", "back", "prev", "previous options",
    "read all", "all options", "all", "read everything",
})

_PAGE_SIZE = 3


class SelectionContext:
    """Remembers the current selection state across turns.

    Used by run.py to enable follow-up commands without re-prompting.
    """

    def __init__(self) -> None:
        self.clear()

    def clear(self) -> None:
        self.active: bool = False
        self.options: list[str] = []
        self.header: str = ""
        self.module: str = ""
        self.search_query: str = ""
        self.timestamp: float = 0.0
        self.timeout: float = 30.0
        self.page: int = 0
        self.page_size: int = _PAGE_SIZE
        self.extra: dict = {}

    def store(
        self,
        options: list[str],
        header: str = "",
        module: str = "",
        search_query: str = "",
        timeout: float = 30.0,
        **extra: object,
    ) -> None:
        self.active = True
        self.options = options
        self.header = header
        self.module = module
        self.search_query = search_query
        self.timestamp = __import__("time").monotonic()
        self.timeout = timeout
        self.page = 0
        self.extra = extra

    @property
    def is_expired(self) -> bool:
        if not self.active:
            return True
        return (__import__("time").monotonic() - self.timestamp) >= self.timeout


class VoiceSelectionManager:
    """
    Presents a list of options and returns the user's selection.

    Usage::

        manager = VoiceSelectionManager(voice_input=my_voice_func)
        choice = manager.select(
            options=["Chrome", "Edge", "Firefox"],
            header="I found multiple browsers.",
        )
        # choice is one of the option strings, or None if cancelled
    """

    _shared_voice_manager: object | None = None

    def __init__(
        self,
        voice_input: Callable[[], str | None] | None = None,
        speak: Callable[[str], None] | None = None,
        engine: object | None = None,
    ) -> None:
        self._voice_input = voice_input
        self._speak = speak or self._default_speak()
        self._engine = engine
        self._context = SelectionContext()

        # Pagination tracking
        self._page = 0
        self._options: list[str] = []
        self._page_size = _PAGE_SIZE

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def select(
        self,
        options: Sequence[str],
        header: str = "Please choose an option.",
        retries: int = 3,
        allow_cancel: bool = True,
        synonyms: dict[str, str] | None = None,
        context: SelectionContext | None = None,
    ) -> str | None:
        """
        Present *options* to the user and return the selected option text.

        Parameters
        ----------
        options:
            The list of choices (e.g. file names, profile names).
        header:
            A descriptive heading shown and spoken before the list.
        retries:
            Maximum number of attempts before giving up.
        allow_cancel:
            Whether the user can say "cancel" to abort.
        synonyms:
            Optional mapping of alternative spoken forms to canonical option text.
        context:
            Optional SelectionContext to store state for follow-up commands.

        Returns
        -------
        The selected option text, or ``None`` if cancelled or retries exhausted.
        """
        if not options:
            logger.warning("VoiceSelectionManager.select() called with empty options")
            return None

        if len(options) == 1:
            return options[0]

        self._options = list(options)
        self._page = 0

        # Store context if provided
        if context is not None:
            context.store(
                options=list(options),
                header=header,
            )

        self._present_paginated(header, list(options), self._page)

        for attempt in range(retries):
            utterance = self._get_utterance()

            if utterance is None:
                utterance = self._text_prompt()

            if not utterance:
                logger.info("VoiceSelectionManager: no input received")
                if attempt < retries - 1:
                    self._say("I didn't catch that. Please try again.")
                    continue
                return None

            reply = utterance.strip()

            # --- Cancel ---
            if allow_cancel and reply.casefold() in _CANCEL_WORDS:
                logger.info("VoiceSelectionManager: cancelled by user")
                return None

            # --- Pagination commands ---
            pagination_result = self._handle_pagination(reply, header, list(options))
            if pagination_result == "retry":
                continue
            if pagination_result == "cancelled":
                return None
            if isinstance(pagination_result, str):
                return pagination_result

            # --- Smart parse ---
            selected = self._smart_parse(reply, list(options))
            if selected is not None:
                logger.info("VoiceSelectionManager: matched '%s' -> '%s'", reply, selected)
                if context is not None:
                    context.clear()
                return selected

            # --- Synonym ---
            if synonyms:
                canonical = synonyms.get(reply.casefold().strip())
                if canonical and canonical in options:
                    if context is not None:
                        context.clear()
                    return canonical

            # --- Name (exact, substring) ---
            selected = self._match_name(reply, list(options))
            if selected is not None:
                logger.info("VoiceSelectionManager: name matched '%s' -> '%s'", reply, selected)
                if context is not None:
                    context.clear()
                return selected

            # --- Retry ---
            if attempt < retries - 1:
                self._say(
                    f"Sorry, I didn't understand '{reply}'. "
                    f"Please say the option number or name."
                )
            else:
                self._say("I could not understand your choice. Please try again later.")

        logger.info("VoiceSelectionManager: retries exhausted")
        if context is not None:
            context.clear()
        return None

    def select_from_context(self, context: SelectionContext) -> str | None:
        """Continue a selection using stored context (for follow-up commands)."""
        if not context.active or context.is_expired:
            return None
        return self.select(
            options=context.options,
            header=context.header,
            context=context,
        )

    # ------------------------------------------------------------------
    # Smart parsing
    # ------------------------------------------------------------------

    _PATTERN_PREFIX = re.compile(
        r"^(?:choose|pick|select|get|open|launch|use|grab)\s+",
        re.IGNORECASE,
    )
    _PATTERN_OPTION = re.compile(
        r"(?:option|number|#)\s*(\d+|" + "|".join(_NUMBER_WORDS) + r")\b",
        re.IGNORECASE,
    )
    _PATTERN_THE = re.compile(
        r"(?:the\s+)?(\w+)\s+(?:one|option|choice)",
        re.IGNORECASE,
    )

    def _smart_parse(self, reply: str, options: list[str]) -> str | None:
        """Parse natural language selection phrases.

        Understands all these forms:
          2, two, option two, option 2, choose option two,
          pick option 2, pick the second one, second, the second one,
          number two, #2, choose the first one, pick the third
        """
        lower = reply.casefold().strip()

        # --- Direct ordinal word: "first", "second" ---
        if lower in _ORDINAL_WORDS:
            idx = _ORDINAL_WORDS[lower]
            if 0 <= idx < len(options):
                return options[idx]

        # --- Direct number word: "two" ---
        if lower in _NUMBER_WORDS:
            idx = _NUMBER_WORDS[lower]
            if 0 <= idx < len(options):
                return options[idx]

        # --- Direct digit: "2" ---
        if lower.isdigit():
            idx = int(lower) - 1
            if 0 <= idx < len(options):
                return options[idx]

        # --- Strip prefixes: "choose ", "pick ", "select ", etc. ---
        stripped = self._PATTERN_PREFIX.sub("", lower).strip()

        # --- "option two", "option 2", "number 2", "#2" ---
        m = self._PATTERN_OPTION.search(stripped)
        if m:
            raw = m.group(1)
            idx = _parse_index(raw)
            if idx is not None and 0 <= idx < len(options):
                return options[idx]

        # --- "the second one", "the first option" ---
        m = self._PATTERN_THE.search(stripped)
        if m:
            word = m.group(1).casefold()
            if word in _ORDINAL_WORDS:
                idx = _ORDINAL_WORDS[word]
                if 0 <= idx < len(options):
                    return options[idx]
            if word in _NUMBER_WORDS:
                idx = _NUMBER_WORDS[word]
                if 0 <= idx < len(options):
                    return options[idx]

        # --- Word-by-word ordinal in stripped: "pick second" -> "second" ---
        for word in stripped.split():
            if word in _ORDINAL_WORDS:
                idx = _ORDINAL_WORDS[word]
                if 0 <= idx < len(options):
                    return options[idx]

        # --- "the second" (standalone ordinal at end) ---
        for word in lower.split():
            if word in _ORDINAL_WORDS:
                idx = _ORDINAL_WORDS[word]
                if 0 <= idx < len(options):
                    return options[idx]

        return None

    # ------------------------------------------------------------------
    # Pagination
    # ------------------------------------------------------------------

    def _handle_pagination(
        self,
        reply: str,
        header: str,
        options: list[str],
    ) -> str | None:
        """Handle pagination commands. Returns:
        - "retry" to continue the retry loop
        - a selected option string if one was matched
        - "cancelled" if cancelled
        - None to continue to other matching strategies
        """
        lower = reply.casefold().strip()

        if lower in ("next", "more", "next options", "show more", "continue"):
            return self._next_page(header, options)

        if lower in ("previous", "prev", "back", "previous options"):
            return self._prev_page(header, options)

        if lower in ("read all", "all options", "all", "read everything"):
            self._present_all(header, options)
            return "retry"

        return None

    def _next_page(self, header: str, options: list[str]) -> str | None:
        max_page = (len(options) - 1) // self._page_size
        if self._page < max_page:
            self._page += 1
            self._present_paginated(header, options, self._page)
            return "retry"
        self._say("There are no more options. Please choose from the current list.")
        return "retry"

    def _prev_page(self, header: str, options: list[str]) -> str | None:
        if self._page > 0:
            self._page -= 1
            self._present_paginated(header, options, self._page)
            return "retry"
        self._say("You are already on the first page.")
        return "retry"

    def _present_paginated(self, header: str, options: list[str], page: int) -> None:
        """Present a single page of options using short format."""
        start = page * self._page_size
        end = min(start + self._page_size, len(options))
        page_options = options[start:end]
        total_pages = (len(options) - 1) // self._page_size + 1

        # Print
        print(f"\n{header}")
        for i, opt in enumerate(page_options, start + 1):
            short = self._shorten_name(opt)
            print(f"  Option {i}: {short}")
        if total_pages > 1:
            print(f"  (Page {page + 1} of {total_pages})")
            print(f"  Say 'next' for more, 'previous' for previous, or 'read all'.")
        print()

        # Speak (short format)
        tts_parts: list[str] = [f"{header}."]
        for i, opt in enumerate(page_options, start + 1):
            word = _NUMBER_NAMES.get(i, str(i))
            short = self._shorten_name(opt)
            tts_parts.append(f"Option {word}: {short}.")
        tts_parts.append("Say the option number or name.")
        self._say(" ".join(tts_parts))

    def _present_all(self, header: str, options: list[str]) -> None:
        """Present all options in short format."""
        print(f"\n{header}")
        for i, opt in enumerate(options, 1):
            short = self._shorten_name(opt)
            print(f"  Option {i}: {short}")
        print()

        tts_parts: list[str] = [f"{header}."]
        for i, opt in enumerate(options, 1):
            word = _NUMBER_NAMES.get(i, str(i))
            short = self._shorten_name(opt)
            tts_parts.append(f"Option {word}: {short}.")
        tts_parts.append("Say the option number or name.")
        self._say(" ".join(tts_parts))

    # ------------------------------------------------------------------
    # Short name formatting
    # ------------------------------------------------------------------

    @staticmethod
    def _shorten_name(name: str, max_words: int = 4, max_chars: int = 30) -> str:
        """Shorten a potentially long filename/label for speech.

        Strips common extensions and truncates long names.
        """
        # Strip common extensions
        for ext in (".pdf", ".docx", ".doc", ".txt", ".exe", ".lnk",
                     ".jpg", ".png", ".gif", ".mp3", ".mp4", ".html"):
            if name.lower().endswith(ext) and len(name) > len(ext) + 1:
                name = name[:-len(ext)]

        # Truncate if too long
        if len(name) > max_chars:
            name = name[:max_chars - 3] + "..."

        # Shorten by word count
        words = name.split()
        if len(words) > max_words:
            return " ".join(words[:max_words]) + "..."

        return name

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _get_utterance(self) -> str | None:
        """Capture voice input, return recognised text or None."""
        if self._voice_input is None:
            return None
        try:
            return self._voice_input()
        except Exception as exc:
            logger.debug("Voice input failed: %s", exc)
            return None

    def _text_prompt(self) -> str | None:
        """Fallback text prompt when voice input is unavailable."""
        try:
            return input("Enter your choice (or 'cancel'): ").strip()
        except (EOFError, KeyboardInterrupt):
            return None

    def _say(self, message: str) -> None:
        """Speak a message via TTS (best-effort)."""
        if self._engine is not None:
            try:
                self._engine.speak(message)
                return
            except Exception as exc:
                logger.debug("Engine TTS failed: %s", exc)
        if self._speak is not None:
            try:
                self._speak(message)
            except Exception as exc:
                logger.debug("TTS failed: %s", exc)
        logger.info("TTS: %s", message)

    # ------------------------------------------------------------------
    # Matching strategies
    # ------------------------------------------------------------------

    @staticmethod
    def _match_name(reply: str, options: list[str]) -> str | None:
        """Match by name: exact, substring, all-words."""
        lower = reply.casefold().strip()
        if not lower:
            return None

        for opt in options:
            if opt.casefold() == lower:
                return opt

        substring_matches = [opt for opt in options if lower in opt.casefold()]
        if len(substring_matches) == 1:
            return substring_matches[0]

        words = lower.split()
        if len(words) > 1:
            for opt in options:
                opt_lower = opt.casefold()
                if all(w in opt_lower for w in words):
                    return opt

        if len(substring_matches) > 1:
            logger.info(
                "VoiceSelectionManager: ambiguous '%s' matches %s",
                reply, substring_matches,
            )

        return None

    # ------------------------------------------------------------------
    # Default TTS (lazy-shared VoiceManager)
    # ------------------------------------------------------------------

    @classmethod
    def _default_speak(cls) -> Callable[[str], None] | None:
        if cls._shared_voice_manager is None:
            try:
                from voice.manager import VoiceManager
                cls._shared_voice_manager = VoiceManager()
            except Exception:
                return None
        return cls._shared_voice_manager.speak


def _parse_index(text: str) -> int | None:
    """Convert a token to a 0-based index (digit or word)."""
    t = text.strip()
    if t.isdigit():
        return int(t) - 1
    return _NUMBER_WORDS.get(t)
