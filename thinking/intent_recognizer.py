from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from brain.parsed_command import ParsedCommand


_INTENT_CATEGORIES: dict[str, str] = {
    "open_app": "navigation",
    "close_app": "system",
    "open_website": "navigation",
    "search": "information",
    "play_music": "playback",
    "play_video": "playback",
    "media_pause": "playback",
    "media_resume": "playback",
    "media_next": "playback",
    "media_previous": "playback",
    "skip_ad": "playback",
    "like_video": "playback",
    "subscribe_channel": "playback",
    "continue_watching": "playback",
    "scroll_page": "navigation",
    "focus_app": "navigation",
    "type_text": "input",
    "hotkey": "input",
    "move_mouse": "input",
    "click": "input",
    "scroll": "input",
    "screenshot": "system",
    "volume": "system",
    "brightness": "system",
    "help": "system",
    "noop": "system",
    "ambiguous": "ambiguous",
    "unknown": "unknown",
}


_INTENT_REQUIRES_CONTEXT: set[str] = {
    "open_app",
    "open_website",
    "search",
    "play_music",
    "play_video",
    "focus_app",
}


_INTENT_REQUIRES_VERIFICATION: set[str] = {
    "open_app",
    "open_website",
    "search",
    "play_music",
}


@dataclass(frozen=True)
class RecognizedIntent:
    raw_text: str
    intent: str
    confidence: float
    entities: dict[str, Any]
    category: str = "unknown"
    requires_context: bool = False
    requires_verification: bool = False
    is_destructive: bool = False
    constraints: dict[str, Any] = field(default_factory=dict)
    reasoning: str = ""


class IntentRecognizer:
    def recognize(self, parsed: ParsedCommand) -> RecognizedIntent:
        intent = parsed.intent
        category = _INTENT_CATEGORIES.get(intent, "unknown")
        requires_context = intent in _INTENT_REQUIRES_CONTEXT
        requires_verification = intent in _INTENT_REQUIRES_VERIFICATION
        is_destructive = self._is_destructive(intent, parsed.entities)
        reasoning = self._build_reasoning(intent, parsed.entities, category)

        constraints: dict[str, Any] = {"safe_to_reuse_tab": not is_destructive}
        if intent == "open_app":
            app_name = parsed.entities.get("app_name", "")
            constraints["is_browser"] = self._is_browser(app_name)
        if intent == "search":
            provider = parsed.entities.get("provider", "google")
            constraints["provider"] = provider
            constraints["has_query"] = bool(parsed.entities.get("query"))
        if intent == "open_website":
            website = parsed.entities.get("website", "")
            constraints["website"] = website
            constraints["is_media_site"] = self._is_media_site(website)
        if intent == "play_music":
            constraints["has_query"] = bool(parsed.entities.get("query"))

        return RecognizedIntent(
            raw_text=parsed.raw_text,
            intent=parsed.intent,
            confidence=parsed.confidence,
            entities=parsed.entities,
            category=category,
            requires_context=requires_context,
            requires_verification=requires_verification,
            is_destructive=is_destructive,
            constraints=constraints,
            reasoning=reasoning,
        )

    @staticmethod
    def _is_destructive(intent: str, entities: dict[str, Any]) -> bool:
        if intent in ("close_app", "hotkey", "close_jarvis", "shutdown_windows", "restart", "shutdown", "delete_file", "format_drive", "kill_process", "close_all_apps"):
            return True
        if intent == "open_app" and entities.get("force_restart"):
            return True
        return False

    @staticmethod
    def _is_browser(app_name: str) -> bool:
        name = app_name.casefold()
        browsers = {"chrome", "msedge", "brave", "opera", "vivaldi", "firefox"}
        return name in browsers or any(b in name for b in browsers)

    @staticmethod
    def _is_media_site(website: str) -> bool:
        site = website.casefold()
        media = {"youtube", "netflix", "spotify", "soundcloud", "twitch", "vimeo"}
        return site in media or any(m in site for m in media)

    @staticmethod
    def _build_reasoning(intent: str, entities: dict[str, Any], category: str) -> str:
        if intent == "open_app":
            app = entities.get("app_name", "unknown")
            return f"User wants to open application '{app}'"
        if intent == "open_website":
            site = entities.get("website", "unknown")
            return f"User wants to navigate to '{site}'"
        if intent == "search":
            query = entities.get("query", "")
            provider = entities.get("provider", "google")
            return f"User wants to search '{query}' on {provider}"
        if intent == "play_music":
            query = entities.get("query", "")
            return f"User wants to play music '{query}'"
        if intent == "close_app":
            app = entities.get("app_name", "unknown")
            return f"User wants to close '{app}'"
        if intent == "close_jarvis":
            return "User wants to shut down JARVIS"
        if intent == "shutdown_windows":
            return "User wants to shut down Windows"
        if intent == "restart":
            return "User wants to restart Windows"
        if intent == "delete_file":
            file_query = entities.get("file_query", "")
            return f"User wants to delete '{file_query}'"
        if intent == "format_drive":
            drive = entities.get("drive", "")
            return f"User wants to format drive '{drive}'"
        if intent == "kill_process":
            proc = entities.get("process", "")
            return f"User wants to kill process '{proc}'"
        if intent == "close_all_apps":
            return "User wants to close all open applications"
        return f"User intent is '{intent}' (category: {category})"
