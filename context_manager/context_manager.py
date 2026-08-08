from __future__ import annotations

import logging
from typing import Any

from context_manager.app_detector import AppDetector
from context_manager.browser_detector import (
    BrowserDetector,
    BrowserInfo,
    BrowserTab,
    BrowserTabMatch,
)
from context_manager.clarification_engine import (
    ClarificationEngine,
    ClarificationType,
    is_media_tab,
)
from models.response import Response

logger = logging.getLogger(__name__)

_SITE_KEYWORD_MAP: dict[str, list[str]] = {
    "youtube": ["youtube", "youtu.be"],
    "chatgpt": ["chatgpt", "chat.openai"],
    "chat gpt": ["chatgpt", "chat.openai"],
    "gmail": ["gmail", "mail.google"],
    "github": ["github"],
    "google": ["google"],
    "wikipedia": ["wikipedia"],
    "amazon": ["amazon"],
    "notion": ["notion"],
    "outlook": ["outlook", "live.com"],
    "maps": ["maps.google", "google.com/maps"],
    "drive": ["drive.google"],
    "docs": ["docs.google"],
    "calendar": ["calendar.google"],
    "meet": ["meet.google"],
    "reddit": ["reddit"],
    "stackoverflow": ["stackoverflow", "stackexchange"],
    "twitter": ["twitter", "x.com"],
    "facebook": ["facebook"],
    "instagram": ["instagram"],
    "linkedin": ["linkedin"],
    "netflix": ["netflix"],
    "spotify": ["spotify", "open.spotify"],
}

_PROTECTED_TAB_PATTERNS: list[str] = [
    "chatgpt", "chat.openai", "chatgpt.com",
    "mail.google", "gmail",
    "docs.google.com/document", "docs.google.com/spreadsheets",
    "docs.google.com/forms", "docs.google.com/presentation",
    "github.com", "gitlab", "bitbucket",
    "bank", "onlinebanking", "internetbanking",
    "paypal", "venmo", "wise.com",
    "vscode.dev", "github.dev", "codespaces",
    "notion.so", "miro.com", "figma.com", "canva.com",
    "overleaf", "colab.research",
    "outlook.office", "office.com", "sharepoint",
    "jira", "confluence", "trello", "asana", "linear",
    "stackoverflow", "stackexchange",
]


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
        elif intent == "play_music":
            return self._check_play_music(entities)

        return None

    def handle_follow_up(self, answer: str) -> Response | None:
        if not self.clarification.has_pending:
            return None

        ctype = self.clarification.pending_type
        context = self.clarification.pending_context

        if ctype == ClarificationType.WHICH_BROWSER:
            return self._handle_which_browser(answer, context)

        resolved = self.clarification.resolve_answer(answer)
        action = resolved.get("action", "unknown")
        context = resolved.get("context", {})
        follow_up_intent = resolved.get("intent", "")

        if action == "unknown":
            return Response(
                success=False,
                message=f"I didn't understand that. {resolved.get('original_question', '')}",
                needs_clarification=True,
                clarification_question=resolved.get("original_question", ""),
            )

        if action == "cancel":
            return Response(
                success=True,
                message="Cancelled.",
                data={"context_resolved": True, "action": "cancel", "intent": follow_up_intent},
            )

        # Handle new action types
        if action == "replace_search":
            return self._build_resolved_response("use_current_tab", {
                **context,
                "query": context.get("query", ""),
                "provider": context.get("provider", "google"),
                "in_current_tab": True,
                "follow_up_intent": "search",
            })

        if action == "search_here":
            return self._build_resolved_response("use_current_tab", {
                **context,
                "query": context.get("query", ""),
                "provider": "youtube",
                "in_current_tab": True,
                "follow_up_intent": "search",
            })

        if action == "search_there":
            return self._build_resolved_response("use_current_tab", {
                **context,
                "query": context.get("query", ""),
                "provider": "google",
                "in_current_tab": True,
                "follow_up_intent": "search",
            })

        if action == "replace_music":
            return self._build_resolved_response("use_current_tab", {
                **context,
                "query": context.get("query", ""),
                "provider": "youtube",
                "in_current_tab": True,
                "follow_up_intent": "search",
            })

        if action == "keep_music":
            return Response(
                success=True,
                message="Keeping the current music playing.",
                data={"context_resolved": True, "action": "continue_current", "intent": follow_up_intent},
            )

        if action == "queue_music":
            return self._build_resolved_response("open_new_tab", {
                **context,
                "website": "youtube",
                "query": context.get("query", ""),
                "provider": "youtube",
                "follow_up_intent": "search",
            })

        context_with_intent = dict(context)
        if follow_up_intent:
            context_with_intent["follow_up_intent"] = follow_up_intent
        return self._build_resolved_response(action, context_with_intent)

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

        is_browser = any(
            b in app_name.casefold() for b in ("chrome", "edge", "brave", "opera", "vivaldi", "firefox")
        )
        if is_browser:
            question = (
                f"{display_name} is already running. Would you like me to "
                "use the existing window, open a new window, or use a different profile?"
            )
        elif has_focusable_window:
            question = f"{display_name} is already running. Would you like me to switch to it or open another window?"
        else:
            question = f"{display_name} is already running in the background. Would you like me to switch to it or open another window?"

        self.clarification.set_pending(
            question=question,
            ctype=ClarificationType.APP_ALREADY_RUNNING,
            context={
                "app_name": app_name,
                "display_name": display_name,
                "process_name": process_name,
            },
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

    def _is_protected_tab(self, url: str, title: str) -> bool:
        url_lower = url.casefold()
        title_lower = title.casefold()
        for pattern in _PROTECTED_TAB_PATTERNS:
            if pattern in url_lower or pattern in title_lower:
                return True
        return False

    def _check_website_open(self, entities: dict[str, Any]) -> Response | None:
        website = entities.get("website", "")
        url = entities.get("url", "")
        site_key = website.strip().casefold()

        keywords = self._get_site_keywords(site_key, url)

        all_matches: list[BrowserTabMatch] = []
        seen: set[tuple[str, int]] = set()
        for kw in keywords:
            for match in self.browser_detector.find_website_across_browsers(kw):
                dedup_key = (match.browser.name, match.tab.id)
                if dedup_key not in seen:
                    seen.add(dedup_key)
                    all_matches.append(match)

        if not all_matches:
            active = self.browser_detector.get_active_tab_across_browsers()
            if active and self._is_protected_tab(active.tab.url, active.tab.title):
                question = f"Your current tab appears to contain protected content. I'll open {website} in a new tab to avoid disturbing it."
                return Response(
                    success=False,
                    message=question,
                    needs_clarification=True,
                    clarification_question=f"{question} Proceed?",
                    data={"website": website, "new_tab": True},
                )
            return None

        browsers_with_site: dict[str, list[BrowserTabMatch]] = {}
        for m in all_matches:
            browsers_with_site.setdefault(m.browser.name, []).append(m)

        unique_browsers = list(browsers_with_site.keys())

        if self._all_active(all_matches):
            match = all_matches[0]
            return self._ask_tab_action(website, BrowserTabMatch(browser=match.browser, tab=match.tab), entities)

        if len(unique_browsers) > 1:
            return self._ask_which_browser(website, unique_browsers, browsers_with_site, all_matches, entities)

        single_match = all_matches[0]
        return self._ask_tab_action(website, single_match, entities)

    def _check_search(self, entities: dict[str, Any]) -> Response | None:
        query = entities.get("query", "")
        provider = entities.get("provider", "google")
        provider_key = provider.strip().casefold()

        # Check if the active tab is YouTube — ask search destination first
        active = self.browser_detector.get_active_tab_across_browsers()
        if active and provider_key == "google":
            active_content = self.browser_detector.classify_tab_content(active.tab)
            if active_content == "video":
                question = f"Your current tab is YouTube. Should I search for '{query}' on YouTube or on Google?"
                self.clarification.set_pending(
                    question=question,
                    ctype=ClarificationType.SEARCH_DESTINATION,
                    context={
                        "query": query,
                        "providers": ["youtube", "google"],
                        "active_content": active_content,
                        "browser_name": active.browser.name,
                        "debug_port": active.browser.debug_port,
                    },
                    follow_up_intent="search",
                )
                return Response(
                    success=False,
                    message=question,
                    needs_clarification=True,
                    clarification_question=question,
                    data={"query": query},
                )

        keywords = self._get_site_keywords(provider_key, "")

        all_matches: list[BrowserTabMatch] = []
        seen: set[tuple[str, int]] = set()
        for kw in keywords:
            for match in self.browser_detector.find_website_across_browsers(kw):
                dedup_key = (match.browser.name, match.tab.id)
                if dedup_key not in seen:
                    seen.add(dedup_key)
                    all_matches.append(match)

        if not all_matches:
            return None

        tab = all_matches[0].tab
        browser_name = all_matches[0].browser.display_name

        # Check if there's already a search results page open for this provider
        search_url_keyword = "search" if provider_key != "youtube" else "results"
        has_search_tab = any(
            search_url_keyword in m.tab.url.casefold() for m in all_matches
        )

        if has_search_tab:
            question = (
                f"I already have a {provider} search open in {browser_name}. "
                f"Would you like to replace the current search, open a new tab, "
                f"or open a new window?"
            )
            self.clarification.set_pending(
                question=question,
                ctype=ClarificationType.SEARCH_ALREADY_OPEN,
                context={
                    "query": query,
                    "provider": provider,
                    "tab_id": tab.id,
                    "window_id": tab.window_id,
                    "browser_name": all_matches[0].browser.name,
                    "browser_display": browser_name,
                    "debug_port": all_matches[0].browser.debug_port,
                },
                follow_up_intent="search",
            )
            return Response(
                success=False,
                message=question,
                needs_clarification=True,
                clarification_question=question,
                data={"query": query, "provider": provider},
            )

        question = f"Should I search for '{query}' in the current {provider} tab on {browser_name} or create a new tab?"
        self.clarification.set_pending(
            question=question,
            ctype=ClarificationType.CURRENT_OR_NEW_TAB,
            context={
                "query": query,
                "provider": provider,
                "tab_id": tab.id,
                "window_id": tab.window_id,
                "browser_name": all_matches[0].browser.name,
                "browser_display": browser_name,
                "debug_port": all_matches[0].browser.debug_port,
            },
            follow_up_intent="search",
        )
        return Response(
            success=False,
            message=question,
            needs_clarification=True,
            clarification_question=question,
            data={"query": query, "provider": provider},
        )

    def _check_play_music(self, entities: dict[str, Any]) -> Response | None:
        query = entities.get("query", "")
        if not query:
            return None

        # Detect if YouTube Music is already open and playing
        active = self.browser_detector.get_active_tab_across_browsers()
        if active:
            active_content = self.browser_detector.classify_tab_content(active.tab)
            if active_content == "music":
                browser_name = active.browser.display_name
                question = (
                    f"I found music already playing in {browser_name}. "
                    f"Would you like to replace the current music, "
                    f"queue {query}, or keep the current playlist?"
                )
                self.clarification.set_pending(
                    question=question,
                    ctype=ClarificationType.MUSIC_PLAYING_CONSUMER,
                    context={
                        "query": query,
                        "browser_name": active.browser.name,
                        "browser_display": browser_name,
                        "debug_port": active.browser.debug_port,
                        "tab_id": active.tab.id,
                        "tab_url": active.tab.url,
                    },
                    follow_up_intent="play_music",
                )
                return Response(
                    success=False,
                    message=question,
                    needs_clarification=True,
                    clarification_question=question,
                    data={"query": query},
                )

        # Check if YouTube is open in any browser tab (not necessarily music)
        yt_matches = self.browser_detector.find_website_across_browsers("youtube")
        if len(yt_matches) == 1:
            match = yt_matches[0]
            display = match.browser.display_name
            question = f"I found YouTube already open in {display}. Would you like to continue there, switch to it, or open another tab?"
            self.clarification.set_pending(
                question=question,
                ctype=ClarificationType.TAB_ALREADY_OPEN,
                context={
                    "website": "youtube",
                    "query": query,
                    "tab_id": match.tab.id,
                    "window_id": match.tab.window_id,
                    "browser_name": match.browser.name,
                    "browser_display": display,
                    "debug_port": match.browser.debug_port,
                    "process_name": match.browser.process_name,
                },
                follow_up_intent="play_music",
            )
            return Response(
                success=False,
                message=question,
                needs_clarification=True,
                clarification_question=question,
                data={"query": query},
            )

        if len(yt_matches) > 1:
            unique = list({m.browser.name for m in yt_matches})
            browsers_with: dict[str, list[BrowserTabMatch]] = {}
            for m in yt_matches:
                browsers_with.setdefault(m.browser.name, []).append(m)
            return self._ask_which_browser("YouTube", unique, browsers_with, yt_matches, entities.get("__raw", {}))

        return None

    # ------------------------------------------------------------------
    # Follow-up handling
    # ------------------------------------------------------------------

    def _handle_which_browser(self, answer: str, context: dict[str, Any]) -> Response | None:
        browsers_in_context = context.get("browsers", [])
        website = context.get("website", "")
        entities = context.get("entities", {})

        selected = self._match_browser_answer(answer, browsers_in_context)
        if not selected:
            browser_names = [b.get("display_name", b.get("name", "")) for b in browsers_in_context]
            question = f"I didn't catch which browser. I found {website} open in {' and '.join(browser_names)}. Which one would you like to use?"
            self.clarification.set_pending(
                question=question,
                ctype=ClarificationType.WHICH_BROWSER,
                context=context,
                follow_up_intent="open_website",
            )
            return Response(
                success=False,
                message=question,
                needs_clarification=True,
                clarification_question=question,
            )

        matches_for_browser = context.get(f"matches_{selected}", [])
        if matches_for_browser:
            match = matches_for_browser[0]
            return self._ask_tab_action(website, BrowserTabMatch(browser=match["browser_info"], tab=match["tab_info"]), entities)

        return None

    def _build_resolved_response(self, action: str, context: dict[str, Any]) -> Response:
        data = {
            "context_resolved": True,
            "action": action,
            "intent": context.get("follow_up_intent", ""),
            "context": context,
        }

        if action in ("switch_to_existing", "switch_to_tab"):
            data["switch_target"] = context.get("process_name") or context.get("app_name", "")
        elif action == "open_new_window":
            data["switch_target"] = context.get("process_name") or context.get("app_name", "")
        elif action == "open_new_tab":
            data["website"] = context.get("website", "")
            data["url"] = context.get("url", "")
            data["debug_port"] = context.get("debug_port")
        elif action == "continue_current":
            data["action"] = "continue_current"

        return Response(success=True, message="", data=data)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _get_site_keywords(self, site_key: str, url: str) -> list[str]:
        mapped = _SITE_KEYWORD_MAP.get(site_key, [])
        if not mapped:
            mapped = [site_key]

        if url:
            from urllib.parse import urlparse
            try:
                parsed = urlparse(url)
                domain = parsed.netloc or parsed.path
                domain = domain.replace("www.", "")
                if domain and domain not in mapped:
                    mapped.append(domain)
            except Exception:
                pass

        return mapped

    def _all_active(self, matches: list[BrowserTabMatch]) -> bool:
        return all(m.tab.active for m in matches)

    def _ask_which_browser(
        self,
        website: str,
        unique_browsers: list[str],
        browsers_with_site: dict[str, list[BrowserTabMatch]],
        all_matches: list[BrowserTabMatch],
        entities: dict[str, Any],
    ) -> Response:
        browser_list = []
        browser_display_names = []
        for bname in unique_browsers:
            display_name = all_matches[0].browser.display_name if bname == all_matches[0].browser.name else ""
            for m in all_matches:
                if m.browser.name == bname:
                    display_name = m.browser.display_name
                    break
            browser_info_obj = None
            for m in all_matches:
                if m.browser.name == bname:
                    browser_info_obj = m.browser
                    break
            browser_list.append({
                "name": bname,
                "display_name": display_name,
                "process_name": browser_info_obj.process_name if browser_info_obj else "",
            })
            browser_display_names.append(display_name)

        question = f"I found {website} open in {' and '.join(browser_display_names)}. Which one would you like to use?"

        context: dict[str, Any] = {
            "website": website,
            "browsers": browser_list,
            "entities": entities,
        }
        for bname in unique_browsers:
            context[f"matches_{bname}"] = [
                {"browser_info": m.browser, "tab_info": m.tab}
                for m in all_matches if m.browser.name == bname
            ]

        self.clarification.set_pending(
            question=question,
            ctype=ClarificationType.WHICH_BROWSER,
            context=context,
            follow_up_intent="open_website",
        )
        return Response(
            success=False,
            message=question,
            needs_clarification=True,
            clarification_question=question,
            data={"website": website, "browsers": browser_display_names},
        )

    def _ask_tab_action(
        self,
        website: str,
        match: BrowserTabMatch,
        entities: dict[str, Any],
    ) -> Response:
        tab = match.tab
        browser = match.browser

        is_media = is_media_tab(tab.title, tab.url)
        has_work = self._tab_has_work_content(tab.title, tab.url)
        display_name = browser.display_name

        if is_media:
            question = f"I found {website} already playing in {display_name}. Would you like to continue there or open another tab?"
            ctype = ClarificationType.MEDIA_PLAYING
        elif has_work:
            question = f"I found {website} already open in {display_name} — the current tab appears to contain work content. Would you like to open a new tab instead, or switch to it anyway?"
            ctype = ClarificationType.TAB_ALREADY_OPEN
        else:
            question = f"I found {website} already open in {display_name}. Would you like me to switch to it or open another tab?"
            ctype = ClarificationType.TAB_ALREADY_OPEN

        context = {
            "website": website,
            "url": entities.get("url", ""),
            "tab_id": tab.id,
            "window_id": tab.window_id,
            "browser_name": browser.name,
            "browser_display": display_name,
            "debug_port": browser.debug_port,
            "process_name": browser.process_name,
        }

        self.clarification.set_pending(
            question=question,
            ctype=ctype,
            context=context,
            follow_up_intent="open_website",
        )
        return Response(
            success=False,
            message=question,
            needs_clarification=True,
            clarification_question=question,
            data={"website": website, "browser": display_name},
        )

    @staticmethod
    def _tab_has_work_content(tab_title: str, tab_url: str) -> bool:
        title_lower = tab_title.casefold()
        url_lower = tab_url.casefold()
        work_patterns = [
            "docs.google.com/document", "docs.google.com/spreadsheets",
            "docs.google.com/forms", "docs.google.com/presentation",
            "github.com", "gitlab", "bitbucket", "stackoverflow",
            "stackexchange", "code.", "codepen", "replit", "codesandbox",
            "overleaf", "notion.so", "miro", "figma", "canva",
            "jira", "confluence", "trello", "asana", "linear",
            "outlook", "office.com", "sharepoint", "teams",
            "google.com/document", "google.com/sheets",
            "colab.research", "kaggle",
        ]
        for pattern in work_patterns:
            if pattern in url_lower:
                return True
        work_title_keywords = [
            "google docs", "google sheets", "google slides", "google forms",
            "microsoft word", "microsoft excel", "microsoft powerpoint",
            "visual studio", "vs code", "intellij", "pycharm",
            "sublime text", "notepad++", "atom",
        ]
        for kw in work_title_keywords:
            if kw in title_lower:
                return True
        return False

    @staticmethod
    def _match_browser_answer(answer: str, browsers: list[dict[str, str]]) -> str | None:
        answer_lower = answer.strip().casefold()
        for b in browsers:
            if answer_lower == b.get("name", "").casefold():
                return b["name"]
            if answer_lower == b.get("display_name", "").casefold():
                return b["name"]
            if answer_lower == b.get("process_name", "").casefold():
                return b["name"]
            disp_words = b.get("display_name", "").lower().split()
            if len(disp_words) > 1 and disp_words[-1].casefold() == answer_lower:
                return b["name"]
            if b.get("name", "").casefold() in answer_lower:
                return b["name"]
            disp = b.get("display_name", "").casefold()
            if disp and disp in answer_lower:
                return b["name"]
            if answer_lower in b.get("name", "").casefold():
                return b["name"]
        return None
