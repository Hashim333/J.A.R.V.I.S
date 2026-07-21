"""
brain/parser.py

Parser turns raw user text into a ParsedCommand using rule-based matching.

Supports: open/close/focus apps, website launching, search, Chrome
profiles, special folders, settings, volume, screenshot, system commands,
and compound commands (e.g. "open Chrome and search ChatGPT").
"""

from __future__ import annotations

import re
import logging
from typing import Any

from brain.parsed_command import ParsedCommand

logger = logging.getLogger(__name__)


class Parser:
    """
    A stateless, rule-based intent parser.
    Its only public method is `parse(text)`.
    """

    # ------------------------------------------------------------------
    # Application synonyms
    # ------------------------------------------------------------------
    _APP_SYNONYMS: dict[str, str] = {
        "chrome": "chrome",
        "google chrome": "chrome",
        "chrome browser": "chrome",
        "browser": "chrome",
        "my browser": "chrome",
        "calculator": "calculator",
        "calc": "calculator",
        "windows calculator": "calculator",
        "notepad": "notepad",
        "paint": "paint",
        "mspaint": "paint",
        "edge": "edge",
        "microsoft edge": "edge",
        "ms edge": "edge",
        "explorer": "explorer",
        "file explorer": "explorer",
        "vscode": "vscode",
        "vs code": "vscode",
        "code": "vscode",
        "visual studio code": "vscode",
        "code editor": "vscode",
        "cmd": "cmd",
        "command prompt": "cmd",
        "cmd prompt": "cmd",
        "powershell": "powershell",
        "terminal": "powershell",
    }

    # ------------------------------------------------------------------
    # Ambiguous phrases
    # ------------------------------------------------------------------
    _AMBIGUOUS_PHRASES: dict[str, dict] = {
        "code": {
            "primary": "vscode",
            "question": "Did you mean Visual Studio Code or another application?",
        },
        "terminal": {
            "primary": "powershell",
            "question": "Did you mean PowerShell or Command Prompt?",
        },
        "browser": {
            "primary": "chrome",
            "question": "Did you mean Google Chrome or Microsoft Edge?",
        },
        "my browser": {
            "primary": "chrome",
            "question": "Did you mean Google Chrome or Microsoft Edge?",
        },
    }

    # ------------------------------------------------------------------
    # Intent trigger words
    # ------------------------------------------------------------------
    _OPEN_VERBS = ("open", "launch", "start", "run")
    _CLOSE_VERBS = ("close", "quit", "exit", "stop", "terminate", "kill")
    _FOCUS_VERBS = ("focus", "switch to", "bring to front", "bring to foreground")
    _RESTART_VERBS = ("restart", "reload", "reopen")
    _MINIMIZE_VERBS = ("minimize", "minimise")
    _MAXIMIZE_VERBS = ("maximize", "maximise")
    _RESTORE_VERBS = ("restore",)
    _SEARCH_VERBS = ("search", "look up", "find", "google", "search for")

    # All command verbs combined for multi-command detection
    _ALL_COMMAND_VERBS: frozenset[str] = frozenset(
        {v for verbs in (_OPEN_VERBS, _CLOSE_VERBS, _FOCUS_VERBS, _RESTART_VERBS, _MINIMIZE_VERBS, _MAXIMIZE_VERBS, _RESTORE_VERBS, _SEARCH_VERBS) for v in verbs}
    )
    _VOLUME_UP = ("increase volume", "raise volume", "turn up volume", "volume up")
    _VOLUME_DOWN = ("decrease volume", "lower volume", "turn down volume", "volume down")
    _UNMUTE = ("unmute", "unmute volume")
    _MUTE = ("mute", "mute volume", "silence")
    _SET_VOLUME_PATTERN = re.compile(r"set volume to\s+(\d+)")
    _SCREENSHOT = ("take screenshot", "capture screen", "screenshot", "take a screenshot", "capture screenshot")
    _LOCK = ("lock", "lock computer", "lock workstation")
    _SHUTDOWN = ("shutdown", "shut down", "shut down the computer", "power off", "turn off")
    _RESTART = ("restart", "reboot", "restart computer", "reboot computer")
    _SLEEP = ("sleep", "suspend", "sleep computer", "put computer to sleep")

    # System operations
    _SIGN_OUT = ("sign out", "log off", "log out")
    _CANCEL_SHUTDOWN = ("cancel shutdown", "cancel restart", "abort shutdown", "abort restart")
    _DELAYED_SHUTDOWN_PATTERN = re.compile(
        r"(?:shutdown|shut\s*down)\s+(?:\w+\s+)*?in\s+(\d+)\s*(minute|minutes|min|mins|hour|hours|second|seconds|sec|secs)?",
        re.IGNORECASE,
    )
    _DELAYED_RESTART_PATTERN = re.compile(
        r"(?:restart|reboot)\s+(?:\w+\s+)*?in\s+(\d+)\s*(minute|minutes|min|mins|hour|hours|second|seconds|sec|secs)?",
        re.IGNORECASE,
    )
    _FORMAT_DRIVE_VERBS = ("format", "format drive", "format disk")
    _KILL_PROCESS_VERBS = ("kill", "kill process", "stop process", "end task")
    _BRIGHTNESS_SET = ("set brightness", "change brightness")
    _BRIGHTNESS_UP = ("increase brightness", "raise brightness", "brightness up")
    _BRIGHTNESS_DOWN = ("decrease brightness", "lower brightness", "brightness down")
    _BRIGHTNESS_PATTERN = re.compile(r"(?:brightness|set brightness|change brightness)\s*(?:to\s+)?(\d+)", re.IGNORECASE)
    _WIFI_ON = ("turn on wifi", "enable wifi", "wifi on", "switch on wifi")
    _WIFI_OFF = ("turn off wifi", "disable wifi", "wifi off", "switch off wifi")
    _BLUETOOTH_ON = ("turn on bluetooth", "enable bluetooth", "bluetooth on", "switch on bluetooth")
    _BLUETOOTH_OFF = ("turn off bluetooth", "disable bluetooth", "bluetooth off", "switch off bluetooth")
    _AIRPLANE_ON = ("turn on airplane mode", "enable airplane mode", "airplane mode on", "switch on airplane mode")
    _AIRPLANE_OFF = ("turn off airplane mode", "disable airplane mode", "airplane mode off", "switch off airplane mode")
    _SYSTEM_STATUS = ("battery status", "battery", "cpu usage", "ram usage", "disk usage", "network usage", "system status")
    _SYSTEM_TOOLS = {
        "task manager": "open_task_manager",
        "device manager": "open_device_manager",
        "control panel": "open_control_panel",
    }

    # Vision / screen understanding commands
    _READ_SCREEN = ("what's on my screen", "what is on my screen", "what do you see",
                    "read screen", "read the screen", "whats on my screen")
    _DESCRIBE_SCREEN = ("describe screen", "describe the screen", "describe what you see",
                        "describe my screen")
    _CLICK_ELEMENT = ("click", "tap", "press", "click on")
    _FIND_ELEMENT = ("find", "locate", "where is")
    _READ_PDF = ("read pdf", "read this pdf", "ocr pdf", "extract text from pdf",
                 "read pdf file")
    _OCR_IMAGE = ("ocr image", "read text from image", "ocr this image",
                  "read text from picture", "extract text from image")
    _READ_ERROR = ("read error", "read error message", "what does the error say",
                   "read error dialog", "read the error")
    _FILL_FORM = ("fill form", "fill field", "type into", "fill in",
                  "enter text in")

    # Security / pentest commands
    _PENTEST_REPORT = ("create pentest report", "create penetration test report", "generate pentest report", "create report")
    _ORGANIZE_SCANS = ("organize scan results", "organise scan results", "organize today's scan results", "organise today's scan results")
    _SUMMARIZE_SCANS = ("summarize scan results", "summarise scan results", "summarize scan", "summarise scan")
    _PENTEST_PROJECT = ("create pentest project", "create pentest project structure", "new pentest project",
                        "setup pentest project", "create project structure")

    # ------------------------------------------------------------------
    # Known websites (subset — full list in BrowserManager)
    # ------------------------------------------------------------------
    _KNOWN_WEBSITES: dict[str, str] = {
        "google": "https://www.google.com",
        "youtube": "https://www.youtube.com",
        "github": "https://github.com",
        "chatgpt": "https://chatgpt.com",
        "chat gpt": "https://chatgpt.com",
        "gmail": "https://mail.google.com",
        "stackoverflow": "https://stackoverflow.com",
        "stack overflow": "https://stackoverflow.com",
        "reddit": "https://www.reddit.com",
        "wikipedia": "https://www.wikipedia.org",
        "twitter": "https://twitter.com",
        "facebook": "https://www.facebook.com",
        "instagram": "https://www.instagram.com",
        "linkedin": "https://www.linkedin.com",
        "amazon": "https://www.amazon.com",
        "netflix": "https://www.netflix.com",
        "spotify": "https://open.spotify.com",
        "maps": "https://maps.google.com",
        "google maps": "https://maps.google.com",
        "drive": "https://drive.google.com",
        "google drive": "https://drive.google.com",
        "docs": "https://docs.google.com",
        "google docs": "https://docs.google.com",
        "calendar": "https://calendar.google.com",
        "google calendar": "https://calendar.google.com",
        "meet": "https://meet.google.com",
        "google meet": "https://meet.google.com",
    }

    # ------------------------------------------------------------------
    # Search providers
    # ------------------------------------------------------------------
    _SEARCH_PROVIDERS: dict[str, str] = {
        "google": "google",
        "youtube": "youtube",
        "yt": "youtube",
        "github": "github",
        "wikipedia": "wikipedia",
        "wiki": "wikipedia",
        "stackoverflow": "stackoverflow",
        "stack overflow": "stackoverflow",
        "bing": "bing",
        "duckduckgo": "duckduckgo",
        "reddit": "reddit",
    }

    # ------------------------------------------------------------------
    # File command verbs
    # ------------------------------------------------------------------
    _FILE_FIND_VERBS = ("find", "locate")
    _FILE_OPEN_FOLDER_PHRASES = (
        "show folder", "show containing folder", "open file location",
        "open containing folder", "show in folder", "show in explorer",
    )
    _FILE_COPY_VERBS = ("copy",)
    _FILE_MOVE_VERBS = ("move",)
    _FILE_RENAME_VERBS = ("rename",)
    _FILE_DELETE_VERBS = ("delete", "remove")
    _FILE_INDICATORS = ("my ", "the ", "this ", "that ")
    _FILE_FORMAT_WORDS = frozenset({
        "pdf", "document", "doc", "word", "spreadsheet", "excel", "xls",
        "presentation", "powerpoint", "ppt", "image", "photo", "picture",
        "video", "movie", "audio", "music", "zip", "archive",
        "text", "txt", "csv", "json", "xml",
        "file", "folder", "report", "invoice", "resume", "cv",
    })
    _FILE_EXT_PATTERN = re.compile(r"^(.+?)\.\w{2,5}$")

    # ------------------------------------------------------------------
    # Special folders
    # ------------------------------------------------------------------
    _SPECIAL_FOLDERS = {
        "downloads": "downloads",
        "download": "downloads",
        "documents": "documents",
        "document": "documents",
        "pictures": "pictures",
        "picture": "pictures",
        "music": "music",
        "musics": "music",
        "videos": "videos",
        "video": "videos",
        "desktop": "desktop",
        "recent": "recent",
        "recent files": "recent",
    }

    # ------------------------------------------------------------------
    # Settings pages
    # ------------------------------------------------------------------
    _SETTINGS_PAGES = {
        "bluetooth": "bluetooth",
        "bluetooth settings": "bluetooth",
        "wifi": "wifi",
        "wifi settings": "wifi",
        "network": "network",
        "network settings": "network",
        "display": "display",
        "display settings": "display",
        "sound": "sound",
        "sound settings": "sound",
        "personalization": "personalization",
        "system": "system",
        "about": "about",
        "update": "windowsupdate",
        "windows update": "windowsupdate",
        "power": "powersleep",
        "power settings": "powersleep",
        "storage": "storagesense",
        "mouse": "mousetouchpad",
        "keyboard": "keyboard",
        "language": "language",
        "date": "dateandtime",
        "time": "dateandtime",
        "sign in": "signinoptions",
        "accounts": "accounts",
        "accessibility": "easeofaccess",
        "privacy": "privacy",
        "default apps": "defaultapps",
        "apps": "appsfeatures",
        "gaming": "gaming-gamedvr",
    }

    # ------------------------------------------------------------------
    # Filler words stripped during normalisation
    # ------------------------------------------------------------------
    _FILLER_WORDS: frozenset[str] = frozenset(
        {
            "please", "kindly", "can you", "could you", "would you",
            "a", "the", "an", "jarvis", "hey jarvis", "ok jarvis",
            "i want", "i want to", "i would like to", "i need to",
            "can", "could", "would", "will", "shall", "do", "does",
            "just", "like", "maybe", "perhaps",
        }
    )

    # Pattern to detect "open <website>" or "<verb> <site>" when the
    # target looks like a known website short name.
    _WEBSITE_PATTERN = re.compile(
        r"^(open|launch|start|run|go to|take me to)\s+(.+)$",
        re.IGNORECASE,
    )

    # Profile patterns
    _PROFILE_PATTERN = re.compile(
        r"(?:with\s+)?(?:profile\s+)?(\d+|[\w\s]+)$", re.IGNORECASE
    )

    # Search pattern: "search <query> on <provider>"
    _SEARCH_ON_PATTERN = re.compile(
        r"search\s+(.+?)\s+on\s+(.+)$", re.IGNORECASE
    )

    # Compound splitter: "open Chrome and search ChatGPT"
    # Non-capturing group so split() does NOT include separator words
    _COMPOUND_SPLITTER = re.compile(r"\s+(?:and|then|,)\s+", re.IGNORECASE)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def parse(self, text: str) -> ParsedCommand:
        normalized = self._normalize(text)
        logger.info("Parser input=%r normalized=%r", text, normalized)
        if not normalized:
            parsed = self._unknown(text)
            logger.info("Parser output intent=%s entities=%r", parsed.intent, parsed.entities)
            return parsed

        # Single-action execution: compound commands are not supported.
        # Each utterance must express exactly one action.
        parsed = self._try_parse(normalized, text)
        if parsed is None:
            # If nothing matched but it starts with "open", try website
            parsed = self._try_website(normalized, text)
        parsed = parsed or self._unknown(text)
        logger.info(
            "Parser output intent=%s confidence=%.2f entities=%r",
            parsed.intent, parsed.confidence, parsed.entities,
        )
        return parsed

    # ------------------------------------------------------------------
    # Compound commands
    # ------------------------------------------------------------------

    def _try_parse_compound(self, normalized: str, raw_text: str) -> ParsedCommand | None:
        """Split compound commands on 'and'/'then' and create multi-step intent."""
        parts = self._COMPOUND_SPLITTER.split(normalized)
        # With non-capturing groups, parts are just the command segments.
        # A compound needs at least 2 parts (2 commands separated by a conjunction).
        if len(parts) < 2:
            return None

        commands: list[ParsedCommand] = []
        for part in parts:
            cmd = self._try_parse(part.strip(), raw_text)
            if cmd is None:
                cmd = self._try_website(part.strip(), raw_text)
            if cmd is None or cmd.intent == "unknown":
                return None
            commands.append(cmd)

        return ParsedCommand(
            raw_text=raw_text,
            intent="compound",
            entities={"commands": commands},
            confidence=min(c.confidence for c in commands),
        )

    # ------------------------------------------------------------------
    # Main parse dispatch
    # ------------------------------------------------------------------

    def _try_parse(self, normalized: str, raw_text: str) -> ParsedCommand | None:
        # Delayed shutdown / restart (before exact-match system commands)
        m = self._DELAYED_SHUTDOWN_PATTERN.search(raw_text)
        if m:
            amount = int(m.group(1))
            unit = (m.group(2) or "minutes").casefold()
            secs = amount * 60 if unit.startswith("min") else amount * 3600 if unit.startswith("hour") else amount
            return ParsedCommand(raw_text=raw_text, intent="shutdown", entities={"delay_seconds": secs})
        m = self._DELAYED_RESTART_PATTERN.search(raw_text)
        if m:
            amount = int(m.group(1))
            unit = (m.group(2) or "minutes").casefold()
            secs = amount * 60 if unit.startswith("min") else amount * 3600 if unit.startswith("hour") else amount
            return ParsedCommand(raw_text=raw_text, intent="restart", entities={"delay_seconds": secs})

        # Sign out / cancel shutdown
        for phrase in self._SIGN_OUT:
            if normalized == phrase:
                return ParsedCommand(raw_text=raw_text, intent="sign_out", entities={})
        for phrase in self._CANCEL_SHUTDOWN:
            if normalized.startswith(phrase):
                return ParsedCommand(raw_text=raw_text, intent="cancel_shutdown", entities={})

        # System commands
        for pattern, intent, entity_fn in [
            (self._LOCK, "lock", lambda m: {}),
            (self._SHUTDOWN, "shutdown", lambda m: {}),
            (self._RESTART, "restart", lambda m: {}),
            (self._SLEEP, "sleep", lambda m: {}),
        ]:
            for phrase in pattern:
                if normalized.startswith(phrase):
                    rest = normalized[len(phrase):].strip()
                    if not rest or rest in ("computer", "the computer", "the system", "system", "pc", "workstation", "down"):
                        return ParsedCommand(raw_text=raw_text, intent=intent, entities={})

        # Screenshot
        for phrase in self._SCREENSHOT:
            if normalized == phrase or normalized.startswith(phrase):
                return ParsedCommand(raw_text=raw_text, intent="screenshot", entities={})

        # Volume
        vol_match = self._SET_VOLUME_PATTERN.search(normalized)
        if vol_match:
            level = int(vol_match.group(1))
            if 0 <= level <= 100:
                return ParsedCommand(raw_text=raw_text, intent="set_volume", entities={"level": level})

        for phrase in self._VOLUME_UP:
            if phrase in normalized:
                return self._volume_cmd(raw_text, "increase_volume", normalized, phrase)
        for phrase in self._VOLUME_DOWN:
            if phrase in normalized:
                return self._volume_cmd(raw_text, "decrease_volume", normalized, phrase)
        for phrase in self._UNMUTE:
            if phrase in normalized:
                return ParsedCommand(raw_text=raw_text, intent="unmute_volume", entities={})
        for phrase in self._MUTE:
            if phrase in normalized:
                return ParsedCommand(raw_text=raw_text, intent="mute_volume", entities={})

        # Close all applications
        if normalized in {"close all applications", "close everything", "close all windows", "close all apps"}:
            return ParsedCommand(raw_text=raw_text, intent="close_all_apps", entities={})

        # Vision / screen understanding (checked before file commands so
        # "find <UI element>" takes priority over "find <file>")
        vision_result = self._parse_vision(normalized, raw_text)
        if vision_result:
            return vision_result

        # File commands: open, find, copy, move, rename, delete
        file_result = self._parse_file_command(normalized, raw_text, raw_text)
        if file_result:
            return file_result

        # System operations (brightness, wifi, bluetooth, status, etc.)
        sys_result = self._parse_system_ops(normalized, raw_text)
        if sys_result:
            return sys_result

        # Search: "search <query> on <provider>" or "search <query>"
        search_result = self._parse_search(normalized, raw_text)
        if search_result:
            return search_result

        # Settings
        settings_result = self._parse_settings(normalized, raw_text)
        if settings_result:
            return settings_result

        # Special folders
        folder_result = self._parse_special_folder(normalized, raw_text)
        if folder_result:
            return folder_result

        # App / website commands
        app_result = self._parse_app_command(normalized, raw_text)
        if app_result:
            return app_result

        return None

    # ------------------------------------------------------------------
    # Search parsing
    # ------------------------------------------------------------------

    def _parse_search(self, normalized: str, raw_text: str) -> ParsedCommand | None:
        """Parse 'search <query> on <provider>' or 'search <query>'."""
        # "search <query> on <provider>"
        match = self._SEARCH_ON_PATTERN.match(normalized)
        if match:
            query = match.group(1).strip()
            provider_raw = match.group(2).strip()
            provider = self._SEARCH_PROVIDERS.get(provider_raw, provider_raw)
            return ParsedCommand(
                raw_text=raw_text,
                intent="search",
                entities={"query": query, "provider": provider},
            )

        # "search <query>" or "search for <query>"
        search_verbs = ("search", "search for", "look up", "find", "google")
        for verb in search_verbs:
            if normalized.startswith(verb) or normalized.startswith(verb + " for"):
                actual_verb = verb if verb.startswith("search") else verb
                rest = normalized[len(actual_verb):].strip()
                if rest.startswith("for "):
                    rest = rest[4:].strip()
                if not rest:
                    continue
                # If rest is a known website, treat it as "open website"
                if rest in self._KNOWN_WEBSITES:
                    return ParsedCommand(
                        raw_text=raw_text,
                        intent="open_website",
                        entities={"website": rest, "url": self._KNOWN_WEBSITES[rest]},
                    )
                return ParsedCommand(
                    raw_text=raw_text,
                    intent="search",
                    entities={"query": rest, "provider": "google"},
                )

        return None

    # ------------------------------------------------------------------
    # Settings
    # ------------------------------------------------------------------

    def _parse_settings(self, normalized: str, raw_text: str) -> ParsedCommand | None:
        match = re.match(r"^open\s+settings\s*$", normalized)
        if match:
            return ParsedCommand(raw_text=raw_text, intent="open_settings", entities={"page": ""})

        match = re.match(r"^open\s+(.+?)\s+settings$", normalized)
        if match:
            page_phrase = match.group(1).strip()
            mapped = self._SETTINGS_PAGES.get(page_phrase)
            return ParsedCommand(
                raw_text=raw_text,
                intent="open_settings",
                entities={"page": mapped or page_phrase},
            )
        return None

    # ------------------------------------------------------------------
    # Special folders
    # ------------------------------------------------------------------

    def _parse_special_folder(self, normalized: str, raw_text: str) -> ParsedCommand | None:
        for phrase, canonical in self._SPECIAL_FOLDERS.items():
            pattern = rf"^open\s+{re.escape(phrase)}\s*$"
            if re.match(pattern, normalized):
                return ParsedCommand(
                    raw_text=raw_text,
                    intent="open_special_folder",
                    entities={"folder": canonical},
                )
        return None

    # ------------------------------------------------------------------
    # File commands
    # ------------------------------------------------------------------

    def _parse_file_command(
        self, normalized: str, raw_text: str, original_text: str = "",
    ) -> ParsedCommand | None:
        """Parse file-related commands.

        Handles: open_file, find_file, open_file_location,
                 copy_file, move_file, rename_file, delete_file.
        """
        source_text = original_text or raw_text

        # --- Open containing folder (checked first because "open file
        # location" starts with "open" which is also an app verb) ---
        for phrase in self._FILE_OPEN_FOLDER_PHRASES:
            if normalized.startswith(phrase):
                rest = normalized[len(phrase):].strip()
                if rest.startswith("containing "):
                    file_query = rest[11:].strip()
                else:
                    file_query = rest
                if file_query:
                    return ParsedCommand(
                        raw_text=raw_text,
                        intent="open_file_location",
                        entities={"file_query": file_query},
                    )
                return ParsedCommand(
                    raw_text=raw_text,
                    intent="open_file_location",
                    entities={},
                )

        # --- Copy / Move / Rename / Delete (unambiguous file verbs) ---

        for verb in self._FILE_COPY_VERBS:
            if normalized.startswith(verb):
                rest = normalized[len(verb):].strip()
                raw_rest = ""
                if source_text.startswith(verb):
                    raw_rest = source_text[len(verb):].strip()
                candidate_rest = raw_rest if raw_rest and " to " in raw_rest else rest
                if " to " in candidate_rest:
                    parts = candidate_rest.split(" to ", 1)
                    source = parts[0].strip()
                    destination = parts[1].strip()
                    if source and destination:
                        return ParsedCommand(
                            raw_text=raw_text,
                            intent="copy_file",
                            entities={"source": source, "destination": destination},
                        )

        for verb in self._FILE_MOVE_VERBS:
            if normalized.startswith(verb):
                rest = normalized[len(verb):].strip()
                raw_rest = ""
                if source_text.startswith(verb):
                    raw_rest = source_text[len(verb):].strip()
                candidate_rest = raw_rest if raw_rest and " to " in raw_rest else rest
                if " to " in candidate_rest:
                    parts = candidate_rest.split(" to ", 1)
                    source = parts[0].strip()
                    destination = parts[1].strip()
                    if source and destination:
                        return ParsedCommand(
                            raw_text=raw_text,
                            intent="move_file",
                            entities={"source": source, "destination": destination},
                        )

        for verb in self._FILE_RENAME_VERBS:
            if normalized.startswith(verb):
                rest = normalized[len(verb):].strip()
                raw_rest = ""
                if source_text.startswith(verb):
                    raw_rest = source_text[len(verb):].strip()
                candidate_rest = raw_rest if raw_rest and " to " in raw_rest else rest
                if " to " in candidate_rest:
                    parts = candidate_rest.split(" to ", 1)
                    source = parts[0].strip()
                    new_name = parts[1].strip()
                    if source and new_name:
                        return ParsedCommand(
                            raw_text=raw_text,
                            intent="rename_file",
                            entities={"source": source, "new_name": new_name},
                        )

        for verb in self._FILE_DELETE_VERBS:
            if normalized.startswith(verb):
                rest = normalized[len(verb):].strip()
                if source_text.startswith(verb):
                    raw_rest = source_text[len(verb):].strip()
                    if raw_rest:
                        rest = raw_rest
                if rest:
                    return ParsedCommand(
                        raw_text=raw_text,
                        intent="delete_file",
                        entities={"file_query": rest},
                    )

        # --- Find / Locate (overlaps with search verb "find") ---
        for verb in self._FILE_FIND_VERBS:
            # Check original text first to preserve dots/fillers
            raw_rest = ""
            if source_text.startswith(verb):
                raw_rest = source_text[len(verb):].strip()
                if raw_rest.startswith("for "):
                    raw_rest = raw_rest[4:].strip()

            rest = normalized[len(verb):].strip() if normalized.startswith(verb) else ""
            if not rest and not raw_rest:
                continue
            if rest.startswith("for "):
                rest = rest[4:].strip()

            candidate = raw_rest if raw_rest else rest
            if not candidate:
                continue

            # File indicators: "find my/the/this/that <file>"
            for indicator in self._FILE_INDICATORS:
                if candidate.startswith(indicator):
                    file_query = candidate[len(indicator):].strip()
                    if file_query:
                        return ParsedCommand(
                            raw_text=raw_text,
                            intent="find_file",
                            entities={"file_query": file_query},
                        )

            # Has a known format word (pdf, word, image, ...)
            # or ends with a file extension
            words = candidate.split()
            has_format = any(
                w.casefold() in self._FILE_FORMAT_WORDS for w in words
            )
            has_ext = (
                bool(self._FILE_EXT_PATTERN.match(words[-1]))
                if words else False
            )
            if has_format or has_ext:
                return ParsedCommand(
                    raw_text=raw_text,
                    intent="find_file",
                    entities={"file_query": candidate},
                )

            # Single-word queries that would otherwise fall through to
            # web search are left to the search parser (e.g. "find
            # python" → web search, not file search).

        # --- Open file (intercepted before app commands) ---
        #
        # Check the ORIGINAL text first because the normaliser strips
        # filler words and dots ("open the invoice.pdf" →
        # "open invoicepdf", losing both "the" and the dot).
        if source_text.startswith("open "):
            original_rest = source_text[5:].strip()
            # "open my/the/this/that <file>" — check raw to catch
            # filler words that the normaliser would remove
            for indicator in self._FILE_INDICATORS:
                if original_rest.startswith(indicator):
                    file_query = original_rest[len(indicator):].strip()
                    if file_query:
                        return ParsedCommand(
                            raw_text=raw_text,
                            intent="open_file",
                            entities={"file_query": file_query},
                        )

            # "open <name>.<ext>" — on original text, not normalised
            if self._FILE_EXT_PATTERN.match(original_rest):
                file_query = self._FILE_EXT_PATTERN.match(original_rest).group(1)
                return ParsedCommand(
                    raw_text=raw_text,
                    intent="open_file",
                    entities={"file_query": original_rest},
                )

        # Also check normalised text for patterns that survive
        # normalisation (e.g. "open invoice pdf" → no dots/fillers).
        if normalized.startswith("open "):
            rest = normalized[5:].strip()
            if rest:
                # "open <...> <format_word>" — e.g. "open invoice pdf"
                words = rest.split()
                if (
                    len(words) >= 2
                    and words[-1].casefold() in self._FILE_FORMAT_WORDS
                ):
                    return ParsedCommand(
                        raw_text=raw_text,
                        intent="open_file",
                        entities={"file_query": rest},
                    )

        return None

    # ------------------------------------------------------------------
    # System operations (brightness, WiFi, Bluetooth, status, tools)
    # ------------------------------------------------------------------

    def _parse_system_ops(self, normalized: str, raw_text: str) -> ParsedCommand | None:
        # --- Brightness ---
        for phrase in self._BRIGHTNESS_UP:
            if phrase in normalized:
                return self._brightness_cmd(raw_text, normalized, phrase, +10)
        for phrase in self._BRIGHTNESS_DOWN:
            if phrase in normalized:
                return self._brightness_cmd(raw_text, normalized, phrase, -10)
        for phrase in self._BRIGHTNESS_SET:
            if phrase in normalized:
                rest = normalized.replace(phrase, "").strip()
                m = re.search(r"(\d+)", rest)
                if m:
                    level = int(m.group(1))
                    return ParsedCommand(raw_text=raw_text, intent="set_brightness", entities={"level": level})
                return ParsedCommand(raw_text=raw_text, intent="set_brightness", entities={"level": 50})
        m = self._BRIGHTNESS_PATTERN.search(normalized)
        if m:
            level = int(m.group(1))
            if 0 <= level <= 100:
                return ParsedCommand(raw_text=raw_text, intent="set_brightness", entities={"level": level})

        # --- WiFi ---
        for phrase in self._WIFI_ON:
            if phrase in normalized:
                return ParsedCommand(raw_text=raw_text, intent="wifi_on", entities={})
        for phrase in self._WIFI_OFF:
            if phrase in normalized:
                return ParsedCommand(raw_text=raw_text, intent="wifi_off", entities={})

        # --- Bluetooth ---
        for phrase in self._BLUETOOTH_ON:
            if phrase in normalized:
                return ParsedCommand(raw_text=raw_text, intent="bluetooth_on", entities={})
        for phrase in self._BLUETOOTH_OFF:
            if phrase in normalized:
                return ParsedCommand(raw_text=raw_text, intent="bluetooth_off", entities={})

        # --- Airplane mode ---
        for phrase in self._AIRPLANE_ON:
            if phrase in normalized:
                return ParsedCommand(raw_text=raw_text, intent="airplane_mode_on", entities={})
        for phrase in self._AIRPLANE_OFF:
            if phrase in normalized:
                return ParsedCommand(raw_text=raw_text, intent="airplane_mode_off", entities={})

        # --- System status ---
        for phrase in self._SYSTEM_STATUS:
            if phrase in normalized:
                query = phrase if phrase != "system status" else "all"
                return ParsedCommand(raw_text=raw_text, intent="system_status", entities={"query": query})
        # "what's using the most CPU" / "whats using the most cpu"
        if re.search(r"(?:what'?s|what\s+is)\s+using\s+(?:the\s+)?most\s+(cpu|ram|memory|disk|network)", normalized, re.IGNORECASE):
            return ParsedCommand(raw_text=raw_text, intent="system_status", entities={"query": "cpu_top"})

        # --- System tools (task manager, device manager, control panel) ---
        # Check raw text first to preserve dots (none needed here, but for
        # consistency with the rest of the parser)
        for phrase, intent in self._SYSTEM_TOOLS.items():
            pattern = rf"^(?:open\s+|launch\s+)?{re.escape(phrase)}\s*$"
            if re.match(pattern, normalized):
                return ParsedCommand(raw_text=raw_text, intent=intent, entities={})
            if normalized.startswith("open ") and phrase in normalized:
                rest = normalized[5:].strip()
                if rest == phrase:
                    return ParsedCommand(raw_text=raw_text, intent=intent, entities={})

        # --- Format drive ---
        for verb in self._FORMAT_DRIVE_VERBS:
            if normalized.startswith(verb):
                rest = normalized[len(verb):].strip()
                # Rest could be "D", "drive D", "D drive", "C:", "C:\"
                drive = rest.replace("drive", "").strip().rstrip(":\\/").upper()
                if drive and len(drive) <= 2:
                    return ParsedCommand(
                        raw_text=raw_text,
                        intent="format_drive",
                        entities={"drive": drive},
                    )
                # No drive specified — still treat as format intent
                return ParsedCommand(
                    raw_text=raw_text,
                    intent="format_drive",
                    entities={"drive": rest or ""},
                )

        # --- Kill process ---
        for verb in self._KILL_PROCESS_VERBS:
            if normalized.startswith(verb):
                rest = normalized[len(verb):].strip()
                if not rest:
                    continue
                # "kill chrome", "kill process chrome" — extract process name
                for prefix in ("process", "the process", "the"):
                    if rest.startswith(prefix):
                        rest = rest[len(prefix):].strip()
                if rest:
                    return ParsedCommand(
                        raw_text=raw_text,
                        intent="kill_process",
                        entities={"process": rest},
                    )

        # --- Security / pentest commands ---
        for phrase in self._PENTEST_REPORT:
            if normalized.startswith(phrase):
                rest_raw = self._extract_rest_raw(raw_text, phrase)
                client = None
                project = None
                if " for " in rest_raw:
                    parts = rest_raw.split(" for ", 1)
                    client = parts[1].strip()
                if " on " in rest_raw:
                    parts = rest_raw.split(" on ", 1)
                    project = parts[1].strip()
                entities: dict[str, Any] = {}
                if client:
                    entities["client_name"] = client
                if project:
                    entities["project_name"] = project
                return ParsedCommand(raw_text=raw_text, intent="create_pentest_report", entities=entities)

        for phrase in self._ORGANIZE_SCANS:
            if normalized.startswith(phrase):
                rest_raw = self._extract_rest_raw(raw_text, phrase)
                entities = {}
                to_text = rest_raw
                if to_text.startswith("to "):
                    to_text = to_text[3:]
                if " to " in to_text:
                    parts = to_text.split(" to ", 1)
                    to_text = parts[1].strip()
                if rest_raw and "project_name" not in entities and to_text != rest_raw:
                    entities["project_name"] = to_text
                if rest_raw and "project_name" not in entities:
                    entities["source_dir"] = rest_raw
                return ParsedCommand(raw_text=raw_text, intent="organize_scan_results", entities=entities)

        for phrase in self._SUMMARIZE_SCANS:
            if normalized.startswith(phrase):
                rest_raw = self._extract_rest_raw(raw_text, phrase)
                entities = {"file_path": rest_raw} if rest_raw else {}
                return ParsedCommand(raw_text=raw_text, intent="summarize_scan_results", entities=entities)

        for phrase in self._PENTEST_PROJECT:
            if normalized.startswith(phrase):
                rest_raw = self._extract_rest_raw(raw_text, phrase)
                entities = {"project_name": rest_raw} if rest_raw else {}
                return ParsedCommand(raw_text=raw_text, intent="create_pentest_project", entities=entities)

        return None

    # ------------------------------------------------------------------
    # Vision / screen understanding
    # ------------------------------------------------------------------

    _UI_ELEMENT_KEYWORDS = frozenset({
        "button", "link", "icon", "tab", "menu", "dialog", "window",
        "field", "box", "checkbox", "radio", "dropdown", "list",
        "bar", "label", "text", "image", "picture", "photo",
        "banner", "popup", "notification", "toast", "panel",
        "toolbar", "sidebar", "footer", "header", "heading",
    })

    def _parse_vision(self, normalized: str, raw_text: str) -> ParsedCommand | None:
        # "what's on my screen" / "read screen"
        for phrase in self._READ_SCREEN:
            if normalized == phrase or normalized.startswith(phrase):
                rest = normalized[len(phrase):].strip()
                entities: dict[str, Any] = {}
                if rest:
                    entities["focus"] = rest
                return ParsedCommand(raw_text=raw_text, intent="read_screen", entities=entities)

        # "describe screen"
        for phrase in self._DESCRIBE_SCREEN:
            if normalized == phrase or normalized.startswith(phrase):
                return ParsedCommand(raw_text=raw_text, intent="describe_screen", entities={})

        # "click <text>" / "click on <text>"
        for verb in ("click on", "click", "tap", "press"):
            if normalized.startswith(verb):
                target = normalized[len(verb):].strip()
                if not target:
                    continue
                return ParsedCommand(raw_text=raw_text, intent="click_element",
                                     entities={"target": self._extract_rest_raw(raw_text, verb)})

        # "find <text>" / "locate <text>" — only match for UI elements
        # (containing a keyword like "button", "field", "icon", etc.)
        # or if "find" / "locate" / "where is" is followed by a
        # short phrase that looks like an on-screen label.
        for verb in ("locate", "where is"):
            if normalized.startswith(verb):
                target = normalized[len(verb):].strip()
                if not target or " on " in target:
                    continue
                if self._looks_like_ui_element(target):
                    return ParsedCommand(raw_text=raw_text, intent="find_element",
                                         entities={"target": self._extract_rest_raw(raw_text, verb)})

        if normalized.startswith("find"):
            target = normalized[4:].strip()
            if target and " on " not in target:
                if self._looks_like_ui_element(target):
                    return ParsedCommand(raw_text=raw_text, intent="find_element",
                                         entities={"target": self._extract_rest_raw(raw_text, "find")})

        # "read pdf <path>" / "ocr pdf <path>"
        for phrase in self._READ_PDF:
            if normalized.startswith(phrase):
                rest_raw = self._extract_rest_raw(raw_text, phrase)
                entities = {"file_path": rest_raw} if rest_raw else {}
                return ParsedCommand(raw_text=raw_text, intent="read_pdf", entities=entities)

        # "ocr image <path>"
        for phrase in self._OCR_IMAGE:
            if normalized.startswith(phrase):
                rest_raw = self._extract_rest_raw(raw_text, phrase)
                entities = {"file_path": rest_raw} if rest_raw else {}
                return ParsedCommand(raw_text=raw_text, intent="ocr_image", entities=entities)

        # "read error" / "read error message"
        for phrase in self._READ_ERROR:
            if normalized == phrase or normalized.startswith(phrase):
                return ParsedCommand(raw_text=raw_text, intent="read_error", entities={})
        # Also check raw text for phrases that contain filler words
        # (e.g. "what does the error say" → "what error say" after normalization)
        raw_lower = raw_text.casefold()
        for phrase in self._READ_ERROR:
            if raw_lower == phrase or raw_lower.startswith(phrase):
                return ParsedCommand(raw_text=raw_text, intent="read_error", entities={})

        # "fill form <field> with <value>"
        for phrase in self._FILL_FORM:
            if normalized.startswith(phrase):
                rest_raw = self._extract_rest_raw(raw_text, phrase)
                entities = {}
                if " with " in rest_raw:
                    parts = rest_raw.split(" with ", 1)
                    entities["field"] = parts[0].strip()
                    entities["value"] = parts[1].strip()
                elif rest_raw:
                    entities["field"] = rest_raw
                return ParsedCommand(raw_text=raw_text, intent="fill_form", entities=entities)

        return None

    def _looks_like_ui_element(self, candidate: str) -> bool:
        """Heuristic: does *candidate* refer to a UI element rather than a file?"""
        words = candidate.split()
        if not words:
            return False
        # Contains a UI keyword
        for w in words:
            if w.casefold() in self._UI_ELEMENT_KEYWORDS:
                return True
        # Very short (1-2 words, likely a button label like "Login" or "Save As")
        if len(words) <= 2 and all(len(w) >= 2 for w in words):
            return True
        return False

    @staticmethod
    def _brightness_cmd(raw_text: str, normalized: str, phrase: str, default_delta: int) -> ParsedCommand:
        rest = normalized.replace(phrase, "").strip()
        m = re.search(r"(\d+)", rest)
        amount = int(m.group(1)) if m else default_delta
        return ParsedCommand(
            raw_text=raw_text,
            intent="set_brightness",
            entities={"level": max(0, min(100, amount))},
        )

    # ------------------------------------------------------------------
    # App / Website commands
    # ------------------------------------------------------------------

    def _parse_app_command(self, normalized: str, raw_text: str) -> ParsedCommand | None:
        # Restart
        for verb in self._RESTART_VERBS:
            if normalized.startswith(verb):
                app_phrase = normalized[len(verb):].strip()
                if not app_phrase:
                    continue
                app_name = self._APP_SYNONYMS.get(app_phrase)
                if app_name:
                    return ParsedCommand(
                        raw_text=raw_text,
                        intent="restart_app",
                        entities={"app_name": app_name, "original_app": app_phrase},
                    )
                return ParsedCommand(
                    raw_text=raw_text,
                    intent="restart_app",
                    entities={"app_name": app_phrase, "original_app": app_phrase},
                )

        # Minimize
        for verb in self._MINIMIZE_VERBS:
            if normalized.startswith(verb):
                app_phrase = normalized[len(verb):].strip()
                if not app_phrase:
                    continue
                app_name = self._APP_SYNONYMS.get(app_phrase)
                if app_name:
                    return ParsedCommand(
                        raw_text=raw_text,
                        intent="minimize_app",
                        entities={"app_name": app_name, "original_app": app_phrase},
                    )
                return ParsedCommand(
                    raw_text=raw_text,
                    intent="minimize_app",
                    entities={"app_name": app_phrase, "original_app": app_phrase},
                )

        # Maximize
        for verb in self._MAXIMIZE_VERBS:
            if normalized.startswith(verb):
                app_phrase = normalized[len(verb):].strip()
                if not app_phrase:
                    continue
                app_name = self._APP_SYNONYMS.get(app_phrase)
                if app_name:
                    return ParsedCommand(
                        raw_text=raw_text,
                        intent="maximize_app",
                        entities={"app_name": app_name, "original_app": app_phrase},
                    )
                return ParsedCommand(
                    raw_text=raw_text,
                    intent="maximize_app",
                    entities={"app_name": app_phrase, "original_app": app_phrase},
                )

        # Restore
        for verb in self._RESTORE_VERBS:
            if normalized.startswith(verb):
                app_phrase = normalized[len(verb):].strip()
                if not app_phrase:
                    continue
                app_name = self._APP_SYNONYMS.get(app_phrase)
                if app_name:
                    return ParsedCommand(
                        raw_text=raw_text,
                        intent="restore_app",
                        entities={"app_name": app_name, "original_app": app_phrase},
                    )
                return ParsedCommand(
                    raw_text=raw_text,
                    intent="restore_app",
                    entities={"app_name": app_phrase, "original_app": app_phrase},
                )

        # Focus
        for verb in self._FOCUS_VERBS:
            if normalized.startswith(verb):
                app_phrase = normalized[len(verb):].strip()
                if not app_phrase:
                    continue
                app_name = self._APP_SYNONYMS.get(app_phrase)
                if app_name:
                    return ParsedCommand(
                        raw_text=raw_text,
                        intent="focus_app",
                        entities={"app_name": app_name, "original_app": app_phrase},
                    )
                return ParsedCommand(
                    raw_text=raw_text,
                    intent="focus_app",
                    entities={"app_name": app_phrase, "original_app": app_phrase},
                )

        # Close
        for verb in self._CLOSE_VERBS:
            if normalized.startswith(verb):
                app_phrase = normalized[len(verb):].strip()
                if not app_phrase:
                    continue
                ambiguous = self._is_ambiguous(app_phrase)
                if ambiguous:
                    return ParsedCommand(
                        raw_text=raw_text,
                        intent="ambiguous",
                        entities={"app_phrase": app_phrase, "question": ambiguous},
                    )
                app_name = self._APP_SYNONYMS.get(app_phrase)
                if app_name:
                    return ParsedCommand(
                        raw_text=raw_text,
                        intent="close_app",
                        entities={"app_name": app_name, "original_app": app_phrase},
                    )
                # Pass through unknown app names (e.g. "close zoom")
                return ParsedCommand(
                    raw_text=raw_text,
                    intent="close_app",
                    entities={"app_name": app_phrase, "original_app": app_phrase},
                )

        # Open / Launch
        for verb in self._OPEN_VERBS:
            if normalized.startswith(verb):
                rest = normalized[len(verb):].strip()
                if not rest:
                    continue

                # Detect garbled multi-command transcripts like
                # "open chrome open chrome open calculator"
                rest = self._extract_single_command(rest)

                profile, rest = self._extract_profile(rest)

                ambiguous = self._is_ambiguous(rest)
                if ambiguous:
                    return ParsedCommand(
                        raw_text=raw_text,
                        intent="ambiguous",
                        entities={"app_phrase": rest, "question": ambiguous},
                    )

                # Check if it's a known website
                if rest in self._KNOWN_WEBSITES:
                    entities: dict[str, Any] = {
                        "website": rest,
                        "url": self._KNOWN_WEBSITES[rest],
                    }
                    if profile:
                        entities["profile"] = profile
                    return ParsedCommand(
                        raw_text=raw_text,
                        intent="open_website",
                        entities=entities,
                    )

                # Check if it's an app
                app_name = self._APP_SYNONYMS.get(rest)
                if app_name:
                    entities = {"app_name": app_name, "original_app": rest}
                    if profile:
                        entities["profile"] = profile
                    return ParsedCommand(
                        raw_text=raw_text,
                        intent="open_app",
                        entities=entities,
                    )

                # Rest might be an app name that is not a known website or app
                # Use it as-is (e.g. "open zoom" → unknown, but passed through)
                entities = {"app_name": rest, "original_app": rest}
                if profile:
                    entities["profile"] = profile
                return ParsedCommand(
                    raw_text=raw_text,
                    intent="open_app",
                    entities=entities,
                )

        return None

    # ------------------------------------------------------------------
    # Website-only fallback
    # ------------------------------------------------------------------

    def _try_website(self, normalized: str, raw_text: str) -> ParsedCommand | None:
        """Try to parse as a website opening command."""
        match = self._WEBSITE_PATTERN.match(normalized)
        if not match:
            return None
        target = match.group(2).strip()

        profile, target = self._extract_profile(target)

        if target in self._KNOWN_WEBSITES:
            entities: dict[str, Any] = {
                "website": target,
                "url": self._KNOWN_WEBSITES[target],
            }
            if profile:
                entities["profile"] = profile
            return ParsedCommand(
                raw_text=raw_text,
                intent="open_website",
                entities=entities,
            )

        # If target has a dot, treat as raw URL
        if "." in target:
            url = f"https://{target}" if not target.startswith(("http://", "https://")) else target
            entities = {"website": target, "url": url}
            if profile:
                entities["profile"] = profile
            return ParsedCommand(
                raw_text=raw_text,
                intent="open_website",
                entities=entities,
            )

        return None

    # ------------------------------------------------------------------
    # Profile extraction
    # ------------------------------------------------------------------

    @staticmethod
    def _extract_profile(text: str) -> tuple[str | None, str]:
        """
        Extract a Chrome profile specification from the end of text.

        Supports:
          "chrome profile 2"       → profile="2",  rest="chrome"
          "chrome profile work"    → profile="work", rest="chrome"
          "chrome with profile 2"  → profile="2",  rest="chrome"
          "chrome with work"       → profile="work", rest="chrome"
          "chrome personal"        → profile="personal", rest="chrome"
          "chrome Personal"        → profile="Personal", rest="chrome"

        Returns (profile_or_None, cleaned_text).
        """
        # "with profile <name>" — most explicit form
        m = re.search(r"\s+with\s+profile\s+(.+)$", text, re.IGNORECASE)
        if m:
            profile = m.group(1).strip()
            rest = text[:m.start()].strip()
            return profile, rest

        # "with <name>" — context-dependent
        m = re.search(r"\s+with\s+(.+)$", text, re.IGNORECASE)
        if m:
            profile = m.group(1).strip()
            rest = text[:m.start()].strip()
            return profile, rest

        # "profile <num|name>" at the end
        m = re.search(r"\s+profile\s+(.+)$", text, re.IGNORECASE)
        if m:
            profile = m.group(1).strip()
            rest = text[:m.start()].strip()
            return profile, rest

        # "<app> <profile>" — trailing single word after known browsers
        # e.g. "chrome personal" → profile="personal", app="chrome"
        # Only applies when:
        #   - The text starts with a known browser name
        #   - The trailing word looks like a profile name (title-case or
        #     known profile keyword)
        _BROWSERS = frozenset({"chrome", "chromium", "google chrome", "edge", "microsoft edge", "brave", "firefox", "opera"})
        text_lower = text.casefold()
        for browser in _BROWSERS:
            if text_lower == browser:
                break  # Single word, no profile
            if text_lower.startswith(browser + " "):
                rest_text = text[len(browser):].strip()
                # Only treat as profile if the trailing part is a single word
                # (not a multi-word app name)
                if " " not in rest_text:
                    profile = rest_text
                    rest = browser
                    return profile, rest

        return None, text

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _volume_cmd(self, raw_text: str, intent: str, normalized: str, phrase: str) -> ParsedCommand:
        rest = normalized.replace(phrase, "").strip()
        amount_match = re.search(r"(\d+)", rest)
        amount = int(amount_match.group(1)) if amount_match else 10
        return ParsedCommand(
            raw_text=raw_text,
            intent=intent,
            entities={"amount": min(amount, 100)},
        )

    def _extract_single_command(self, text: str) -> str:
        """If text contains multiple command verbs, keep only the first command.

        Handles garbled transcripts like "chrome open chrome open calculator"
        by splitting on any command verb and returning the first segment.
        """
        words = text.split()
        for i, word in enumerate(words):
            if word in self._ALL_COMMAND_VERBS and i > 0:
                logger.info("Detected multi-command transcript, truncating at %r", word)
                return " ".join(words[:i])
        return text

    def _is_ambiguous(self, app_phrase: str) -> str | None:
        key = app_phrase.strip().casefold()
        entry = self._AMBIGUOUS_PHRASES.get(key)
        if entry:
            return entry["question"]
        return None

    def _normalize(self, text: str) -> str:
        if not text:
            return ""

        normalized = text.casefold()
        normalized = re.sub(r"[^\w\s]", "", normalized)

        sorted_fillers = sorted(self._FILLER_WORDS, key=len, reverse=True)
        pattern = r"\b(" + "|".join(re.escape(word) for word in sorted_fillers) + r")\b"
        normalized = re.sub(pattern, "", normalized, flags=re.IGNORECASE)

        normalized = " ".join(normalized.split())

        # Deduplicate repeated phrases ("open chrome open chrome" -> "open chrome")
        tokens = normalized.split()
        if len(tokens) > 1 and len(tokens) % 2 == 0:
            mid = len(tokens) // 2
            if tokens[:mid] == tokens[mid:]:
                tokens = tokens[:mid]
                normalized = " ".join(tokens)

        return normalized

    @staticmethod
    def _extract_rest_raw(raw_text: str, phrase: str) -> str:
        """Extract the portion of *raw_text* that follows a case‑folded *phrase*.

        This preserves the original punctuation, paths, etc. that
        ``_normalize`` would strip.
        """
        idx = raw_text.casefold().find(phrase)
        if idx < 0:
            return raw_text
        return raw_text[idx + len(phrase):].strip()

    @staticmethod
    def _unknown(raw_text: str) -> ParsedCommand:
        return ParsedCommand(
            raw_text=raw_text,
            intent="unknown",
            confidence=0.0,
            entities={},
        )
