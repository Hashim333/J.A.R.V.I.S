from __future__ import annotations

import logging
from typing import Any

from context_manager.app_detector import AppDetector, WindowState
from context_manager.browser_detector import BrowserDetector, BrowserTab
from context_manager.clarification_engine import (
    ClarificationEngine,
    ClarificationState,
    ClarificationType,
)
from models.response import Response

logger = logging.getLogger(__name__)


class ContextManager:
    def __init__(self) -> None:
        self.app_detector = AppDetector()
        self.browser_detector = BrowserDetector()
        self.clarification = ClarificationEngine()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def check_before_execution(self, intent: str, entities: dict[str, Any], raw_text: str) -> Response | None:
        self.clarification.store_last_command(raw_text)

        if intent == "open_app":
            return self._check_app_open(entities)
        elif intent == "open_website":
            return self._check_website_open(entities)
        elif intent == "search":
            return self._check_search(entities)

        return None

    def handle_follow_up(self, answer: str) -> Response | None:
        if not self.clarification.has_pending:
            return None

        resolved = self.clarification.resolve_answer(answer)
        action = resolved.get("action", "unknown")
        context = resolved.get("context", {})
        intent = resolved.get("intent", "")

        if action == "unknown":
            return Response(
                success=False,
                message=f"I didn't understand that. {resolved.get('original_question', '')}",
                needs_clarification=True,
                clarification_question=resolved.get("original_question", ""),
            )

        return Response(
            success=True,
            message="",
            data={
                "context_resolved": True,
                "action": action,
                "intent": intent,
                "context": context,
            },
        )

    def has_pending_question(self) -> bool:
        return self.clarification.has_pending

    def get_pending_question(self) -> str:
        return self.clarification.pending_question

    # ------------------------------------------------------------------
    # App checks
    # ------------------------------------------------------------------

    def _check_app_open(self, entities: dict[str, Any]) -> Response | None:
        app_name = entities.get("app_name") or entities.get("original_app", "")
        process_name = entities.get("process_name", f"{app_name}.exe")
        display_name = entities.get("original_app", app_name)

        status = self.app_detector.detect(process_name, display_name)

        if not status.running:
            return None

        focusable = [w for w in status.windows if w.title]
        has_focusable_window = bool(focusable)
        is_focused = any(w.is_focused and w.is_visible for w in status.windows)

        if is_focused:
            msg = f"{display_name} is already running and focused."
            return Response(success=True, message=msg)

        if has_focusable_window:
            question = f"{display_name} is already running. Would you like me to switch to it or open another window?"
            self.clarification.set_pending(
                question=question,
                ctype=ClarificationType.APP_ALREADY_RUNNING,
                context={"app_name": app_name, "display_name": display_name, "process_name": process_name},
                follow_up_intent="open_app",
            )
            return Response(
                success=False,
                message=question,
                needs_clarification=True,
                clarification_question=question,
                data={"app_name": app_name, "display_name": display_name},
            )

        question = f"{display_name} is already running in the background. Would you like me to switch to it or open another window?"
        self.clarification.set_pending(
            question=question,
            ctype=ClarificationType.APP_ALREADY_RUNNING,
            context={"app_name": app_name, "display_name": display_name, "process_name": process_name},
            follow_up_intent="open_app",
        )
        return Response(
            success=False,
            message=question,
            needs_clarification=True,
            clarification_question=question,
            data={"app_name": app_name, "display_name": display_name},
        )

    # ------------------------------------------------------------------
    # Website / browser checks
    # ------------------------------------------------------------------

    _SITE_TO_TAB_KEYWORDS: dict[str, str] = {
        "youtube": "youtube",
        "chatgpt": "chatgpt",
        "chat gpt": "chatgpt",
        "gmail": "gmail",
        "github": "github",
        "google": "google",
        "maps": "maps",
        "google maps": "maps",
        "drive": "drive",
        "google drive": "drive",
        "docs": "docs",
        "google docs": "docs",
        "calendar": "calendar",
        "google calendar": "calendar",
        "meet": "meet",
        "google meet": "meet",
        "reddit": "reddit",
        "stackoverflow": "stackoverflow",
        "wikipedia": "wikipedia",
        "linkedin": "linkedin",
        "twitter": "twitter",
        "facebook": "facebook",
        "instagram": "instagram",
        "amazon": "amazon",
        "netflix": "netflix",
        "spotify": "spotify",
    }

    def _check_website_open(self, entities: dict[str, Any]) -> Response | None:
        website = entities.get("website", "")
        url = entities.get("url", "")
        site_key = website.strip().casefold()

        keyword = self._SITE_TO_TAB_KEYWORDS.get(site_key, site_key)
        existing = self.browser_detector.find_tab_by_url(keyword)
        if not existing:
            existing = self.browser_detector.find_tab_by_title(keyword)
        if not existing and url:
            existing = self.browser_detector.find_tab_by_url(url)

        if not existing:
            return None

        if existing.active:
            return Response(
                success=True,
                message=f"You already have {website} open in the active tab.",
            )

        question = f"I found an existing {website} tab. Would you like me to switch to it or open another tab?"
        self.clarification.set_pending(
            question=question,
            ctype=ClarificationType.TAB_ALREADY_OPEN,
            context={"website": website, "url": url, "tab_id": existing.id, "window_id": existing.window_id},
            follow_up_intent="open_website",
        )
        return Response(
            success=False,
            message=question,
            needs_clarification=True,
            clarification_question=question,
            data={"website": website, "url": url},
        )

    def _check_search(self, entities: dict[str, Any]) -> Response | None:
        query = entities.get("query", "")
        provider = entities.get("provider", "google")
        provider_key = provider.strip().casefold()

        keyword = self._SITE_TO_TAB_KEYWORDS.get(provider_key, provider_key)
        existing = self.browser_detector.find_tab_by_url(keyword)

        if existing:
            question = f"Should I search for '{query}' in the current {provider} tab or create a new tab?"
            self.clarification.set_pending(
                question=question,
                ctype=ClarificationType.CURRENT_OR_NEW_TAB,
                context={"query": query, "provider": provider, "tab_id": existing.id, "window_id": existing.window_id},
                follow_up_intent="search",
            )
            return Response(
                success=False,
                message=question,
                needs_clarification=True,
                clarification_question=question,
                data={"query": query, "provider": provider},
            )

        return None
