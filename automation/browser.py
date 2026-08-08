"""
automation/browser.py

DOM-driven browser automation over the Chrome DevTools Protocol.

Every operation runs against a Chrome instance that exposes a DevTools
port (see ``automation.browser_service`` — JARVIS launches its own managed
Chrome with ``--remote-debugging-port`` when none is open).  Tabs are
enumerated, reused, activated and closed through CDP HTTP endpoints, and
pages are read/manipulated with ``Runtime.evaluate`` on the DOM plus the
accessibility tree.

No OCR, no screen coordinates and no image matching anywhere in this module.
"""

from __future__ import annotations

import logging
import time
from urllib.parse import quote_plus, urlparse

from automation.browser_service import get_browser_service, stop_browser_service
from automation.cdp import CdpBrowser, CdpError, CdpTab

logger = logging.getLogger(__name__)


class BrowserOperationError(Exception):
    """Raised when a browser operation fails."""


# ---------------------------------------------------------------------------
# Known websites
# ---------------------------------------------------------------------------

_KNOWN_URLS: dict[str, str] = {
    "google": "https://www.google.com",
    "youtube": "https://www.youtube.com",
    "github": "https://github.com",
    "chatgpt": "https://chatgpt.com",
    "gmail": "https://mail.google.com",
    "facebook": "https://www.facebook.com",
    "instagram": "https://www.instagram.com",
    "linkedin": "https://www.linkedin.com",
}

_SEARCH_URLS: dict[str, str] = {
    "google": "https://www.google.com/search?q={query}",
    "youtube": "https://www.youtube.com/results?search_query={query}",
    "github": "https://github.com/search?q={query}",
    "wikipedia": "https://en.wikipedia.org/w/index.php?search={query}",
    "stackoverflow": "https://stackoverflow.com/search?q={query}",
    "gmail": "https://mail.google.com/mail/u/0/#search/{query}",
    "facebook": "https://www.facebook.com/search/top/?q={query}",
    "instagram": "https://www.instagram.com/explore/search/keyword/?q={query}",
    "linkedin": "https://www.linkedin.com/search/results/all/?keywords={query}",
}


# ---------------------------------------------------------------------------
# Low-level access
# ---------------------------------------------------------------------------


def _client() -> CdpBrowser:
    return get_browser_service().client


def _ok(message: str, **details: object) -> dict:
    result: dict = {"success": True, "message": message}
    if details:
        result["details"] = details
    return result


def _fail(message: str) -> dict:
    return {"success": False, "message": message}


def _ensure_available() -> None:
    try:
        _client()
    except Exception as exc:
        raise BrowserOperationError(f"Browser automation unavailable: {exc}") from exc


def _tab_host(url: str) -> str:
    return urlparse(url).netloc.removeprefix("www.")


def _search_reuse_fragment(provider: str) -> str:
    """Return the URL fragment that identifies an existing search tab.

    YouTube searches may only reuse a *results* tab (never a playing video
    tab); other providers may reuse any tab on their domain.
    """
    if provider == "youtube":
        return "youtube.com/results"
    base = _SEARCH_URLS.get(provider, "")
    if not base:
        return ""
    return _tab_host(base)


def _wait_until_url_contains(
    cdp: CdpBrowser,
    tab: CdpTab,
    fragment: str,
    timeout: float = 8.0,
) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            state = cdp.page_state(tab)
        except CdpError:
            state = {}
        if fragment.casefold() in state.get("url", "").casefold():
            return True
        time.sleep(0.4)
    return False


# ---------------------------------------------------------------------------
# Page interaction
# ---------------------------------------------------------------------------


def open_url(url: str, open_in_new_tab: bool = False) -> dict:
    """Open *url*, reusing an existing tab on the same site when possible.

    SAFETY: a tab is never duplicated — an existing tab on the site's
    domain is activated instead of opening a second copy.
    """
    normalized = _normalize_url(url)
    _ensure_available()
    cdp = _client()
    try:
        existing = None if open_in_new_tab else cdp.find_tab(url_substring=_tab_host(normalized))
    except CdpError as exc:
        return _fail(f"Could not inspect browser tabs ({exc}).")

    if existing is not None:
        try:
            cdp.activate(existing)
        except CdpError as exc:
            return _fail(f"Could not focus the existing tab ({exc}).")
        return _ok(f"Focused the existing tab for {normalized}.", url=normalized, reused=True)

    try:
        tab = cdp.new_tab(normalized)
    except CdpError as exc:
        return _fail(f"Could not open {normalized} ({exc}).")
    if tab is None:
        return _fail(f"Could not open a new tab for {normalized}.")
    return _ok(f"Opened {normalized}.", url=normalized, reused=False)


def search(provider: str, query: str) -> dict:
    """Search *provider* for *query*, reusing an existing search tab.

    Only one search tab per provider is ever created.  A second search of
    the same provider navigates the existing search tab instead of opening
    a duplicate.
    """
    provider_key = provider.strip().casefold()
    template = _SEARCH_URLS.get(provider_key)
    if not template:
        return _fail(f"Unsupported search provider: {provider!r}.")
    if not isinstance(query, str) or not query.strip():
        return _fail("Search query must be a non-empty string.")

    search_url = template.format(query=quote_plus(query.strip()))
    _ensure_available()
    cdp = _client()
    reuse_fragment = _search_reuse_fragment(provider_key)

    try:
        exact = cdp.find_tab(url_substring=search_url)
        if exact is not None:
            cdp.activate(exact)
            return _ok(f"Searched {provider} for {query!r} (existing tab).", url=search_url, reused=True)
        existing = cdp.find_tab(url_substring=reuse_fragment) if reuse_fragment else None
        if existing is not None:
            cdp.navigate(existing, search_url)
            cdp.activate(existing)
            _wait_until_url_contains(cdp, existing, _tab_host(search_url), timeout=6.0)
            return _ok(f"Searched {provider} for {query!r}.", url=search_url, reused=True)
        tab = cdp.new_tab(search_url)
    except CdpError as exc:
        return _fail(f"Could not search {provider} ({exc}).")

    if tab is None:
        return _fail("Could not open a search tab.")
    try:
        cdp.activate(tab)
    except CdpError:
        pass
    return _ok(f"Searched {provider} for {query!r}.", url=search_url, reused=False)


# ---------------------------------------------------------------------------
# Tab management
# ---------------------------------------------------------------------------


def new_tab() -> dict:
    _ensure_available()
    cdp = _client()
    try:
        tab = cdp.new_tab("about:blank")
    except CdpError as exc:
        return _fail(f"Could not open a new tab ({exc}).")
    if tab is None:
        return _fail("Could not open a new tab.")
    return _ok("Opened a new tab.")


def close_current_tab() -> dict:
    _ensure_available()
    cdp = _client()
    try:
        tab = cdp.active_tab()
    except CdpError as exc:
        return _fail(f"Could not read browser tabs ({exc}).")
    if tab is None:
        return _fail("There is no tab to close.")
    try:
        cdp.close_tab(tab)
    except CdpError as exc:
        return _fail(f"Could not close the tab ({exc}).")
    return _ok("Closed the current tab.")


def close_all_tabs() -> dict:
    _ensure_available()
    cdp = _client()
    try:
        tabs = cdp.list_tabs()
        for tab in tabs:
            try:
                cdp.close_tab(tab)
            except CdpError:
                pass
    except CdpError as exc:
        return _fail(f"Could not close the tabs ({exc}).")
    return _ok("Closed all browser tabs.")


def close_other_tabs() -> dict:
    _ensure_available()
    cdp = _client()
    try:
        tabs = cdp.list_tabs()
        active = cdp.active_tab()
        for tab in tabs:
            if active is not None and tab.tab_id == active.tab_id:
                continue
            try:
                cdp.close_tab(tab)
            except CdpError:
                pass
    except CdpError as exc:
        return _fail(f"Could not close the other tabs ({exc}).")
    return _ok("Closed all other tabs.")


def close_specific_tab(tab: int) -> dict:
    if not isinstance(tab, int) or not 1 <= tab <= 8:
        raise BrowserOperationError("Tab number must be 1-8.")
    _ensure_available()
    cdp = _client()
    try:
        tabs = cdp.list_tabs()
        if tab > len(tabs):
            return _fail(f"There is no tab {tab}.")
        cdp.close_tab(tabs[tab - 1])
    except CdpError as exc:
        return _fail(f"Could not close tab {tab} ({exc}).")
    return _ok(f"Closed tab {tab}.")


def switch_tab(tab: int | None = None) -> dict:
    if tab is None:
        return next_tab()
    if not isinstance(tab, int) or not 1 <= tab <= 8:
        raise BrowserOperationError("Tab number must be 1-8.")
    _ensure_available()
    cdp = _client()
    try:
        tabs = cdp.list_tabs()
        if tab > len(tabs):
            return _fail(f"There is no tab {tab}.")
        cdp.activate(tabs[tab - 1])
    except CdpError as exc:
        return _fail(f"Could not switch to tab {tab} ({exc}).")
    return _ok(f"Switched to tab {tab}.")


def next_tab() -> dict:
    _ensure_available()
    cdp = _client()
    try:
        tabs = cdp.list_tabs()
        if len(tabs) < 2:
            return _ok("There is only one tab open.")
        active = cdp.active_tab()
        idx = next((i for i, t in enumerate(tabs) if t.tab_id == (active.tab_id if active else "")), -1)
        target = tabs[(idx + 1) % len(tabs)]
        cdp.activate(target)
    except CdpError as exc:
        return _fail(f"Could not switch tabs ({exc}).")
    return _ok("Switched to the next tab.")


def previous_tab() -> dict:
    _ensure_available()
    cdp = _client()
    try:
        tabs = cdp.list_tabs()
        if len(tabs) < 2:
            return _ok("There is only one tab open.")
        active = cdp.active_tab()
        idx = next((i for i, t in enumerate(tabs) if t.tab_id == (active.tab_id if active else "")), 0)
        target = tabs[(idx - 1) % len(tabs)]
        cdp.activate(target)
    except CdpError as exc:
        return _fail(f"Could not switch tabs ({exc}).")
    return _ok("Switched to the previous tab.")


def duplicate_tab() -> dict:
    _ensure_available()
    cdp = _client()
    try:
        active = cdp.active_tab()
        if active is None:
            return _fail("There is no tab to duplicate.")
        tab = cdp.new_tab(active.url)
        if tab is not None:
            cdp.activate(tab)
    except CdpError as exc:
        return _fail(f"Could not duplicate the tab ({exc}).")
    return _ok("Duplicated the current tab.")


def reopen_closed_tab() -> dict:
    return _fail("Chrome's DevTools protocol cannot reopen a closed tab.")


def refresh_page(hard: bool = False) -> dict:
    _ensure_available()
    cdp = _client()
    try:
        tab = cdp.active_tab()
        if tab is None:
            return _fail("There is no tab to refresh.")
        cdp.reload(tab, ignore_cache=hard)
    except CdpError as exc:
        return _fail(f"Could not refresh the page ({exc}).")
    return _ok("Refreshed the page.")


def reload() -> dict:
    return refresh_page(hard=False)


def back() -> dict:
    return _history("-1", "Went back.")


def forward() -> dict:
    return _history("1", "Went forward.")


def _history(delta: str, message: str) -> dict:
    _ensure_available()
    cdp = _client()
    try:
        tab = cdp.active_tab()
        if tab is None:
            return _fail("There is no browser tab open.")
        cdp.evaluate(tab, f"history.go({delta}); true")
    except CdpError as exc:
        return _fail(f"Could not navigate history ({exc}).")
    return _ok(message)


# ---------------------------------------------------------------------------
# Page state / reading
# ---------------------------------------------------------------------------


def current_state() -> dict:
    """Return the active tab's URL, title, selected text and DOM summary."""
    _ensure_available()
    cdp = _client()
    try:
        tab = cdp.active_tab()
        if tab is None:
            return {"success": False, "message": "No browser tab is open."}
        state = cdp.page_state(tab)
        ax = cdp.accessibility_tree(tab)
    except CdpError as exc:
        return {"success": False, "message": f"Could not read the page ({exc})."}
    return {
        "success": True,
        "message": "Current page state.",
        "details": {
            "url": state.get("url", ""),
            "title": state.get("title", ""),
            "selected_text": state.get("selectedText", ""),
            "ready_state": state.get("readyState", ""),
            "tab": tab.tab_id,
            "ax_nodes": len(ax),
        },
    }


def current_url() -> str:
    """Return the active tab's URL, or ``""`` when no tab is open."""
    _ensure_available()
    cdp = _client()
    try:
        tab = cdp.active_tab()
        if tab is None:
            return ""
        return cdp.page_state(tab).get("url", "")
    except CdpError:
        return ""


def selected_text() -> str:
    """Return the text currently selected on the active tab."""
    _ensure_available()
    cdp = _client()
    try:
        tab = cdp.active_tab()
        if tab is None:
            return ""
        return cdp.page_state(tab).get("selectedText", "")
    except CdpError:
        return ""


def scroll(direction: str = "down") -> dict:
    """Scroll the active tab using the DOM (no mouse, no coordinates)."""
    direction = (direction or "down").casefold()
    if direction == "top":
        js = "window.scrollTo({top: 0, behavior: 'smooth'}); true"
    elif direction == "bottom":
        js = "window.scrollTo({top: document.body.scrollHeight, behavior: 'smooth'}); true"
    else:
        sign = -600 if "up" in direction else 600
        js = f"window.scrollBy({{top: {sign}, behavior: 'smooth'}}); true"

    _ensure_available()
    cdp = _client()
    try:
        tab = cdp.active_tab()
        if tab is None:
            return {"success": False, "message": "No browser tab is open."}
        cdp.activate(tab)
        ok = bool(cdp.evaluate(tab, js))
    except CdpError as exc:
        return {"success": False, "message": f"Could not scroll the page ({exc})."}
    if not ok:
        return {"success": False, "message": "Could not scroll the page."}
    return {"success": True, "message": "Scrolled the page.", "details": {"direction": direction}}


def tabs() -> list[CdpTab]:
    _ensure_available()
    return _client().list_tabs()


def activate_tab(tab: CdpTab) -> bool:
    _ensure_available()
    return _client().activate(tab)


def evaluate(expression: str) -> object:
    """Evaluate *expression* on the active tab (returns the DOM value)."""
    _ensure_available()
    cdp = _client()
    tab = cdp.active_tab()
    if tab is None:
        return None
    return cdp.evaluate(tab, expression)


def accessibility_tree() -> list[dict]:
    """Return a compact accessibility-tree snapshot of the active tab."""
    _ensure_available()
    cdp = _client()
    tab = cdp.active_tab()
    if tab is None:
        return []
    return cdp.accessibility_tree(tab)


# ---------------------------------------------------------------------------
# Lifecycle
# ---------------------------------------------------------------------------


def stop_browser() -> bool:
    """Stop the managed browser (used during JARVIS shutdown)."""
    return stop_browser_service()


# ---------------------------------------------------------------------------
# URL helpers
# ---------------------------------------------------------------------------


def _normalize_url(url: str) -> str:
    if not isinstance(url, str) or not url.strip():
        raise BrowserOperationError("URL must be a non-empty string.")
    target = url.strip()
    key = target.casefold()
    if key in _KNOWN_URLS:
        return _KNOWN_URLS[key]
    if target.startswith(("http://", "https://")):
        return target
    if "." in target:
        return f"https://{target}"
    raise BrowserOperationError(
        f"Unsupported website {url!r}. Use a full URL or a known website name."
    )
