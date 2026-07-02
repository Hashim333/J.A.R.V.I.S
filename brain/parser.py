"""
brain/parser.py

Parser turns raw user text into a ParsedCommand.

The parser is organized around intents and synonym groups. Voice input
and typed input use the same path: text in, ParsedCommand out.
"""

from __future__ import annotations

import re
from collections.abc import Iterable

from models.parsed_command import ParsedCommand


class Parser:
    """Stateless intent parser. Exposes parse(text) only."""

    _SUPPORTED_APPS: dict[str, str] = {
        "notepad": "notepad",
        "calculator": "calculator",
        "calc": "calculator",
        "google chrome": "chrome",
        "chrome": "chrome",
        "edge": "edge",
        "microsoft edge": "edge",
        "firefox": "firefox",
        "mozilla firefox": "firefox",        
        "vscode": "Code.exe",
        "vs code": "Code.exe",
        "visual studio code": "vscode",
        "terminal": "terminal",
        "windows terminal": "terminal",
        "cmd": "cmd",
        "command prompt": "cmd",
        "powershell": "powershell",
        "power shell": "powershell",
        "task manager": "task_manager",
        "settings": "settings",
        "control panel": "control_panel",
        "explorer": "explorer",
        "file explorer": "explorer",
        "paint": "paint",
        "mspaint": "paint",
        "word": "word",
        "microsoft word": "word",
        "excel": "excel",
        "microsoft excel": "excel",
        "powerpoint": "powerpoint",
        "power point": "powerpoint",
        "microsoft powerpoint": "powerpoint",
        "spotify": "spotify",
        "discord": "discord",
        "steam": "steam",
    }

    _WEBSITES: dict[str, str] = {
        "google": "https://www.google.com",
        "youtube": "https://www.youtube.com",
        "chatgpt": "https://chatgpt.com",
        "github": "https://github.com",
        "gmail": "https://mail.google.com",
    }

    _SEARCH_PROVIDERS: frozenset[str] = frozenset(
        {"google", "youtube", "github", "stackoverflow", "wikipedia"}
    )

    _SEARCH_ALIASES: dict[str, str] = {
        "stack overflow": "stackoverflow",
    }

    # Application Management: all app-control phrases collapse into app intents.
    _APP_INTENTS: dict[str, tuple[str, ...]] = {
        "open_app": ("open", "launch", "run", "start", "boot"),
        "close_app": ("close", "quit", "exit", "terminate", "kill"),
        "close_all_app_instances": (
            "close all",
            "quit all",
            "terminate all",
            "kill all",
        ),
        "is_running": (
            "is",
            "check",
            "check if",
            "verify",
            "verify if",
            "is running",
            "is open",
        ),
        "restart_app": ("restart", "reopen", "reload app"),
        "focus_app": ("focus", "bring up", "activate"),
        "minimize_app": ("minimize", "hide"),
        "maximize_app": ("maximize", "full screen"),
        "restore_app": ("restore", "unminimize"),
        "switch_to_app": ("switch to", "go to", "show me"),
    }

    # Browser: tab/navigation/search phrases map to browser intents.
    _BROWSER_INTENTS: dict[str, tuple[str, ...]] = {
        "open_website": ("open website", "open site", "go to", "navigate to"),
        "browser_search": ("search for", "search", "find", "look up"),
        "new_tab": ("new tab", "open new tab"),
        "close_current_tab": ("close tab", "close current tab"),
        "close_specific_tab": ("close tab number", "close specific tab"),
        "close_all_tabs": ("close all tabs",),
        "close_other_tabs": ("close other tabs",),
        "next_tab": ("next tab",),
        "previous_tab": ("previous tab",),
        "switch_tab": ("switch tab", "go to tab"),
        "duplicate_tab": ("duplicate tab",),
        "reopen_closed_tab": ("reopen tab", "reopen closed tab"),
        "reload": ("reload", "refresh"),
        "hard_refresh": ("hard refresh",),
        "back": ("back", "go back"),
        "forward": ("forward", "go forward"),
    }

    # Keyboard: spoken key commands map to reusable keyboard intents.
    _KEYBOARD_INTENTS: dict[str, tuple[str, ...]] = {
        "type_text": ("type", "write", "enter text", "input"),
        "press_key": ("press", "tap"),
        "press_enter": ("press enter", "hit enter", "enter"),
        "press_escape": ("press escape", "hit escape", "escape", "esc"),
        "press_tab": ("press tab", "hit tab", "tab"),
        "backspace": ("backspace", "press backspace"),
        "delete": ("delete", "press delete"),
        "copy": ("copy", "control c", "ctrl c", "ctrl+c"),
        "paste": ("paste", "control v", "ctrl v", "ctrl+v"),
        "select_all": ("select all", "control a", "ctrl a", "ctrl+a"),
        "undo": ("undo", "control z", "ctrl z", "ctrl+z"),
        "hotkey": ("hotkey", "shortcut"),
        "hold_key": ("hold", "hold key"),
        "release_key": ("release", "release key"),
    }

    # Mouse: pointer movement/click/scroll phrases map to mouse intents.
    _MOUSE_INTENTS: dict[str, tuple[str, ...]] = {
        "move_mouse": ("move mouse", "move cursor"),
        "move_relative": ("move relative", "move mouse relative"),
        "left_click": ("left click", "click"),
        "right_click": ("right click",),
        "double_click": ("double click",),
        "drag_mouse": ("drag", "drag mouse"),
        "drop": ("drop", "release mouse"),
        "scroll_up": ("scroll up",),
        "scroll_down": ("scroll down",),
    }

    # Windows: window-management phrases map to window intents.
    _WINDOW_INTENTS: dict[str, tuple[str, ...]] = {
        "active_window": ("what is the active window", "what window is active", "active window"),
        "list_windows": ("list all windows", "show all windows", "list windows"),
        "focus_window": ("focus window", "focus"),
        "move_window": ("move window",),
        "resize_window": ("resize window",),
        "minimize_window": ("minimize window",),
        "maximize_window": ("maximize window",),
        "restore_window": ("restore window",),
        "close_window": ("close window",),
        "close_all_windows": ("close all windows",),
    }

    # Files: common folder/file operations map to file intents.
    _FILE_INTENTS: dict[str, tuple[str, ...]] = {
        "open_downloads": ("open downloads", "downloads folder"),
        "open_documents": ("open documents", "documents folder"),
        "open_desktop": ("open desktop", "desktop folder"),
        "open_folder": ("open folder",),
        "create_folder": ("create folder", "make folder", "new folder"),
        "delete_file": ("delete file", "remove file"),
        "rename_file": ("rename file",),
        "copy_file": ("copy file",),
        "move_file": ("move file",),
    }

    # System: dangerous power/session commands are parsed but not executed silently.
    _SYSTEM_INTENTS: dict[str, tuple[str, ...]] = {
        "lock_pc": ("lock pc", "lock computer", "lock screen"),
        "sleep": ("sleep", "put computer to sleep"),
        "restart_system": ("restart computer", "restart pc", "reboot"),
        "shutdown": ("shutdown", "shut down", "turn off computer"),
        "log_out": ("log out", "sign out"),
        "volume_up": ("volume up", "increase volume"),
        "volume_down": ("volume down", "decrease volume"),
        "mute": ("mute",),
        "unmute": ("unmute",),
        "brightness_up": ("brightness up", "increase brightness"),
        "brightness_down": ("brightness down", "decrease brightness"),
    }

    # Media: media playback phrases map to media intents.
    _MEDIA_INTENTS: dict[str, tuple[str, ...]] = {
        "play_media": ("play",),
        "pause_media": ("pause",),
        "resume_media": ("resume",),
        "next_media": ("next", "next track"),
        "previous_media": ("previous", "previous track"),
        "mute_media": ("mute media",),
        "set_volume": ("set volume", "volume"),
    }

    _DANGEROUS_INTENTS = {
        "shutdown",
        "restart_system",
        "log_out",
        "close_all_app_instances",
        "close_all_windows",
    }

    _FILLER_PREFIXES: tuple[str, ...] = (
        "hey jarvis",
        "hi jarvis",
        "hello jarvis",
        "ok jarvis",
        "okay jarvis",
        "jarvis",
        "please",
        "kindly",
        "could you",
        "would you",
        "can you",
        "will you",
        "would you please",
        "could you please",
        "can you please",
        "please can you",
        "please could you",
        "please would you",
        "just",
        "simply",
    )

    _FILLER_SUFFIXES: tuple[str, ...] = (
        "for me",
        "please",
        "kindly",
    )

    _FILLER_WORDS: frozenset[str] = frozenset(
        {
            "please",
            "kindly",
            "just",
            "simply",
        }
    )

    def parse(self, text: str) -> ParsedCommand:
        if text is None:
            text = ""

        normalized = self._normalize(text)
        if not normalized:
            return self._unknown(text)

        parsed = (
            self._parse_browser(normalized, text)
            or self._parse_keyboard(normalized, text)
            or self._parse_mouse(normalized, text)
            or self._parse_app(normalized, text)
            or self._parse_window(normalized, text)
            or self._parse_window(normalized, text)
            or self._parse_files(normalized, text)
            or self._parse_system(normalized, text)
            or self._parse_media(normalized, text)
        )
        return parsed or self._unknown(text)

    def _parse_app(self, normalized: str, raw_text: str) -> ParsedCommand | None:
        match = self._match_intent(normalized, self._APP_INTENTS)
        if match is not None:
            intent, remainder = match
            remainder = self._clean_remainder(remainder)
            app = self._extract_app(normalized) or self._extract_app(remainder)
            if app is None:
                return None

            return self._command(raw_text, intent, {"app": app})
        return None

    def _parse_browser(self, normalized: str, raw_text: str) -> ParsedCommand | None:
        # Pattern: "search <query> on <provider>"
        match_on = re.match(r"search\s+(.+)\s+on\s+([\w\s]+)", normalized, re.IGNORECASE)
        if match_on:
            query, provider_phrase = match_on.groups()
            provider = self._resolve_search_provider(provider_phrase)
            if provider:
                return self._command(raw_text, "browser_search", {"provider": provider, "query": query.strip()})

        # Pattern: "<provider> <query>"
        for provider_phrase in sorted(list(self._SEARCH_PROVIDERS) + list(self._SEARCH_ALIASES.keys()), key=len, reverse=True):
            if normalized.startswith(f"{provider_phrase} "):
                provider = self._resolve_search_provider(provider_phrase)
                query = normalized[len(provider_phrase):].strip()
                if provider and query:
                    return self._command(raw_text, "browser_search", {"provider": provider, "query": query})

        match = self._match_intent(normalized, self._BROWSER_INTENTS)
        if match is not None:
            intent, remainder = match
            remainder = self._clean_remainder(remainder)
            
            if intent == "open_website":
                target = remainder or self._extract_known_website(normalized)
                if not target:
                    return None
                return self._command(raw_text, intent, {"url": self._normalize_url(target)})

            entities: dict[str, object] = {}
            tab_number = self._first_int(remainder)
            if tab_number is not None:
                entities["tab"] = tab_number
            return self._command(raw_text, intent, entities)

        website = self._extract_known_website(normalized)
        if website and normalized.startswith(("open ", "go ")):
            return self._command(raw_text, "open_website", {"url": website})

        generic_website = self._extract_generic_website(normalized)
        if generic_website and normalized.startswith(("open ", "go ")):
            return self._command(
                raw_text,
                "open_website",
                {"url": self._normalize_url(generic_website)},
            )
        return None

    def _parse_keyboard(self, normalized: str, raw_text: str) -> ParsedCommand | None:
        fixed_hotkeys = {
            "copy": ["ctrl", "c"],
            "paste": ["ctrl", "v"],
            "select_all": ["ctrl", "a"],
            "undo": ["ctrl", "z"],
        }

        match = self._match_intent(normalized, self._KEYBOARD_INTENTS)
        if match is not None:
            intent, remainder = match

            remainder = self._clean_remainder(remainder)
            if intent == "type_text":
                if not remainder:
                    return None
                return self._command(raw_text, intent, {"text": remainder})
            if intent == "press_key":
                if not remainder:
                    return None
                return self._command(raw_text, intent, {"key": remainder})
            if intent in fixed_hotkeys:
                return self._command(raw_text, "hotkey", {"keys": fixed_hotkeys[intent]})
            if intent == "hotkey":
                keys = self._parse_hotkey(remainder)
                if not keys:
                    return None
                return self._command(raw_text, intent, {"keys": keys})
            if intent in {"hold_key", "release_key"}:
                if not remainder:
                    return None
                key_intent = "hold_key" if intent == "hold_key" else "release_key"
                return self._command(raw_text, key_intent, {"key": remainder})
            return self._command(raw_text, intent, {})
        return None

    def _parse_mouse(self, normalized: str, raw_text: str) -> ParsedCommand | None:
        match = self._match_intent(normalized, self._MOUSE_INTENTS)
        if match is not None:
            intent, remainder = match
            remainder = self._clean_remainder(remainder)
            entities: dict[str, object] = {}
            numbers = [int(value) for value in re.findall(r"-?\d+", remainder)]
            if intent == "move_relative" and len(numbers) >= 2:
                entities.update({"dx": numbers[0], "dy": numbers[1]})
            elif intent in {"move_mouse", "drag_mouse"} and len(numbers) >= 2:
                entities.update({"x": numbers[0], "y": numbers[1]})
            elif intent in {"scroll_up", "scroll_down"}:
                amount = numbers[0] if numbers else 5
                entities["amount"] = amount if intent == "scroll_up" else -amount

            return self._command(raw_text, intent, entities)
        return None

    def _parse_window(self, normalized: str, raw_text: str) -> ParsedCommand | None:
        match = self._match_intent(normalized, self._WINDOW_INTENTS)
        if match:
            intent, remainder = match
            remainder = self._clean_remainder(remainder)
            entities: dict[str, object] = {}
            if intent == "focus_window":
                app_name = self._extract_app(remainder)
                if not app_name and not remainder:
                    return None # 'focus' with no target
                entities["title"] = app_name or remainder
            return self._command(raw_text, intent, entities)
        return None

    def _parse_window(self, normalized: str, raw_text: str) -> ParsedCommand | None:
        return self._parse_simple_group(normalized, raw_text, self._WINDOW_INTENTS)

    def _parse_files(self, normalized: str, raw_text: str) -> ParsedCommand | None:
        return self._parse_simple_group(normalized, raw_text, self._FILE_INTENTS)

    def _parse_system(self, normalized: str, raw_text: str) -> ParsedCommand | None:
        return self._parse_simple_group(normalized, raw_text, self._SYSTEM_INTENTS)

    def _parse_media(self, normalized: str, raw_text: str) -> ParsedCommand | None:
        return self._parse_simple_group(normalized, raw_text, self._MEDIA_INTENTS)

    def _parse_simple_group(
        self,
        normalized: str,
        raw_text: str,
        intents: dict[str, tuple[str, ...]],
    ) -> ParsedCommand | None:
        match = self._match_intent(normalized, intents)
        if match is not None:
            intent, remainder = match
            remainder = self._clean_remainder(remainder)
            entities: dict[str, object] = {}
            if remainder:
                entities["target"] = remainder
            return self._command(raw_text, intent, entities)
        return None

    def _command(
        self,
        raw_text: str,
        intent: str,
        entities: dict[str, object],
    ) -> ParsedCommand:
        if intent in self._DANGEROUS_INTENTS:
            entities = {**entities, "requires_confirmation": True}
        return ParsedCommand(
            raw_text=raw_text,
            intent=intent,
            confidence=1.0,
            entities=entities,
        )

    @staticmethod
    def _unknown(raw_text: str) -> ParsedCommand:
        return ParsedCommand(
            raw_text=raw_text,
            intent="unknown",
            confidence=0.0,
            entities={},
        )

    @staticmethod
    def _normalize(text: str) -> str:
        normalized = text.casefold()
        normalized = re.sub(r"[^\w\s+.-]", " ", normalized)
        normalized = " ".join(normalized.split())
        if not normalized:
            return ""

        normalized = Parser._strip_filler_phrases(normalized, Parser._FILLER_PREFIXES, from_start=True)
        normalized = Parser._strip_filler_phrases(normalized, Parser._FILLER_SUFFIXES, from_start=False)
        words = [word for word in normalized.split() if word not in Parser._FILLER_WORDS]
        return " ".join(words)

    @staticmethod
    def _strip_filler_phrases(
        text: str,
        phrases: Iterable[str],
        *,
        from_start: bool,
    ) -> str:
        changed = True
        while changed:
            changed = False
            for phrase in sorted(phrases, key=len, reverse=True):
                if from_start:
                    if text == phrase:
                        return ""
                    if text.startswith(f"{phrase} "):
                        text = text[len(phrase) :].strip()
                        changed = True
                        break
                else:
                    if text == phrase:
                        return ""
                    if text.endswith(f" {phrase}"):
                        text = text[: -len(phrase)].strip()
                        changed = True
                        break
        return text

    @staticmethod
    def _match_leading_synonym(
        text: str,
        synonyms: Iterable[str],
    ) -> str | None:
        for synonym in sorted(synonyms, key=len, reverse=True):
            normalized_synonym = " ".join(synonym.casefold().split())
            if text == normalized_synonym:
                return ""
            if text.startswith(f"{normalized_synonym} "):
                return text[len(normalized_synonym) :].strip()
        return None

    @classmethod
    def _match_intent(
        cls,
        text: str,
        intents: dict[str, tuple[str, ...]],
    ) -> tuple[str, str] | None:
        candidates: list[tuple[str, str]] = []
        for intent, synonyms in intents.items():
            for synonym in synonyms:
                candidates.append((intent, synonym))

        for intent, synonym in sorted(candidates, key=lambda item: len(item[1]), reverse=True):
            matched = cls._match_leading_synonym(text, (synonym,))
            if matched is not None:
                return intent, matched
        return None

    @staticmethod
    def _clean_remainder(text: str) -> str:
        return re.sub(r"^(the|a|an|to|for|if)\s+", "", text).strip()

    def _resolve_search_provider(self, phrase: str) -> str | None:
        """Normalize a search provider phrase."""
        key = phrase.strip().casefold()
        if key in self._SEARCH_PROVIDERS:
            return key
        return self._SEARCH_ALIASES.get(key)

    def _extract_app(self, text: str) -> str | None:
        for phrase, app in sorted(self._SUPPORTED_APPS.items(), key=lambda item: len(item[0]), reverse=True):
            if re.search(rf"\b{re.escape(phrase)}\b", text):
                return app
        return None

    def _extract_known_website(self, text: str) -> str | None:
        for phrase, url in self._WEBSITES.items():
            if re.search(rf"\b{re.escape(phrase)}\b", text):
                return url
        return None

    @staticmethod
    def _extract_generic_website(text: str) -> str | None:
        match = re.search(
            r"\b(?:open|go)\s+(?:to\s+)?([a-z0-9-]+(?:\.[a-z0-9-]+)+)\b",
            text,
        )
        return match.group(1) if match else None

    @staticmethod
    def _normalize_url(target: str) -> str:
        target = target.strip()
        if target.startswith(("http://", "https://")):
            return target
        if "." in target:
            return f"https://{target}"
        return target

    @staticmethod
    def _first_int(text: str) -> int | None:
        match = re.search(r"\d+", text)
        return int(match.group(0)) if match else None

    @staticmethod
    def _parse_hotkey(text: str) -> list[str]:
        if not text:
            return []
        cleaned = text.replace("+", " ").replace(",", " ")
        return [part for part in cleaned.split() if part]
