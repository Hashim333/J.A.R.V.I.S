"""
automation/cdp.py — Chrome DevTools Protocol client.

The single transport layer for all browser automation in JARVIS.  It talks
to a Chrome instance that exposes a DevTools port and drives pages through
the DOM and the accessibility tree — never through OCR, screen coordinates,
or image matching.

Two protocols are used:

- **HTTP** (``/json`` family): enumerate tabs, activate a tab, open a new
  tab, close a tab.
- **WebSocket** (per page target): run ``Runtime.evaluate`` on the page's
  DOM, read the page state (URL / title / selected text), snapshot the
  ``Accessibility.getFullAXTree`` tree, and issue ``Page.navigate`` /
  ``Page.reload``.

A tab is ``CdpTab`` — the stable identifier for every high-level action.
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass
from typing import Any
from urllib.parse import quote

import requests
import websocket

logger = logging.getLogger(__name__)


class CdpError(Exception):
    """Raised when a DevTools endpoint is unreachable or returns an error."""


@dataclass(frozen=True)
class CdpTab:
    """A page target discovered through ``/json``."""

    tab_id: str
    title: str
    url: str
    active: bool
    window_id: int
    ws_url: str


_PAGE_STATE_JS = """
(() => {
  let selectedText = '';
  try { selectedText = (window.getSelection() || {}).toString() || ''; } catch (e) {}
  return {
    url: location.href,
    title: document.title || '',
    selectedText: selectedText,
    readyState: document.readyState,
  };
})()
"""


def _send(ws: websocket.WebSocket, method: str, params: dict[str, Any], msg_id: int = 1) -> dict[str, Any]:
    """Send one CDP command over an open WebSocket and wait for its reply."""
    ws.send(json.dumps({"id": msg_id, "method": method, "params": params}))
    while True:
        message = json.loads(ws.recv())
        if message.get("id") != msg_id:
            continue
        if message.get("error"):
            raise CdpError(f"CDP {method} failed: {message['error']}")
        return message.get("result", {})


class CdpBrowser:
    """Thin CDP client for a single DevTools endpoint (``host:port``)."""

    def __init__(self, port: int, host: str = "127.0.0.1") -> None:
        self._port = int(port)
        self._host = host

    # ------------------------------------------------------------------
    # Endpoint metadata
    # ------------------------------------------------------------------

    @property
    def port(self) -> int:
        return self._port

    @property
    def base_url(self) -> str:
        return f"http://{self._host}:{self._port}"

    def is_reachable(self, timeout: float = 0.8) -> bool:
        try:
            resp = requests.get(f"{self.base_url}/json/version", timeout=timeout)
            return resp.status_code == 200
        except Exception:
            return False

    def version(self) -> dict[str, Any]:
        try:
            resp = requests.get(f"{self.base_url}/json/version", timeout=1.0)
            resp.raise_for_status()
            return resp.json()
        except requests.RequestException as exc:
            raise CdpError(f"DevTools endpoint unreachable on port {self._port}: {exc}") from exc

    # ------------------------------------------------------------------
    # Tab inventory / selection
    # ------------------------------------------------------------------

    def list_tabs(self) -> list[CdpTab]:
        """Return every page target currently open in the browser."""
        try:
            resp = requests.get(f"{self.base_url}/json", timeout=1.5)
            resp.raise_for_status()
            entries = resp.json()
        except requests.RequestException as exc:
            raise CdpError(f"Could not list tabs on port {self._port}: {exc}") from exc

        tabs: list[CdpTab] = []
        for entry in entries if isinstance(entries, list) else []:
            if not isinstance(entry, dict):
                continue
            if entry.get("type") not in (None, "page"):
                continue
            tabs.append(CdpTab(
                tab_id=str(entry.get("id", "")),
                title=str(entry.get("title", "") or ""),
                url=str(entry.get("url", "") or ""),
                active=bool(entry.get("active", False)),
                window_id=int(entry.get("windowId", 0) or 0),
                ws_url=str(entry.get("webSocketDebuggerUrl", "") or ""),
            ))
        return tabs

    def find_tab(
        self,
        url_substring: str | None = None,
        title_substring: str | None = None,
    ) -> CdpTab | None:
        """Return the first tab matching a URL or title fragment.

        URL matches win over title matches so reusing a specific page (e.g.
        the YouTube results page) is deterministic.
        """
        tabs = self.list_tabs()
        if url_substring:
            fragment = url_substring.casefold()
            for tab in tabs:
                if fragment in tab.url.casefold():
                    return tab
        if title_substring:
            fragment = title_substring.casefold()
            for tab in tabs:
                if fragment in tab.title.casefold():
                    return tab
        return None

    def active_tab(self) -> CdpTab | None:
        tabs = self.list_tabs()
        for tab in tabs:
            if tab.active:
                return tab
        return tabs[0] if tabs else None

    # ------------------------------------------------------------------
    # Tab lifecycle
    # ------------------------------------------------------------------

    def activate(self, tab: CdpTab) -> bool:
        try:
            resp = requests.get(f"{self.base_url}/json/activate/{tab.tab_id}", timeout=2.0)
            return resp.status_code == 200
        except requests.RequestException as exc:
            raise CdpError(f"Could not activate tab {tab.tab_id}: {exc}") from exc

    def new_tab(self, url: str = "about:blank") -> CdpTab | None:
        try:
            resp = requests.put(
                f"{self.base_url}/json/new?{quote(url, safe='')}",
                timeout=3.0,
            )
            if resp.status_code != 200:
                logger.warning("cdp.new_tab: /json/new returned %s", resp.status_code)
                return None
            entry = resp.json()
        except requests.RequestException as exc:
            raise CdpError(f"Could not open a new tab: {exc}") from exc
        return CdpTab(
            tab_id=str(entry.get("id", "")),
            title=str(entry.get("title", "") or ""),
            url=str(entry.get("url", "") or url),
            active=True,
            window_id=int(entry.get("windowId", 0) or 0),
            ws_url=str(entry.get("webSocketDebuggerUrl", "") or ""),
        )

    def close_tab(self, tab: CdpTab) -> bool:
        try:
            resp = requests.get(f"{self.base_url}/json/close/{tab.tab_id}", timeout=2.0)
            return resp.status_code == 200
        except requests.RequestException as exc:
            raise CdpError(f"Could not close tab {tab.tab_id}: {exc}") from exc

    # ------------------------------------------------------------------
    # Page-level navigation
    # ------------------------------------------------------------------

    def navigate(self, tab: CdpTab, url: str) -> bool:
        result = self._ws_call(tab, "Page.navigate", {"url": url})
        if result.get("errorText"):
            logger.warning("cdp.navigate: %s", result.get("errorText"))
            return False
        return True

    def reload(self, tab: CdpTab, ignore_cache: bool = False) -> None:
        self._ws_call(tab, "Page.reload", {"ignoreCache": ignore_cache})

    # ------------------------------------------------------------------
    # DOM / evaluation
    # ------------------------------------------------------------------

    def evaluate(self, tab: CdpTab, expression: str, await_promise: bool = True) -> Any:
        """Evaluate *expression* in the page and return its value.

        Returns ``None`` when the expression throws or the result is not
        serialisable with ``returnByValue``.
        """
        result = self._ws_call(tab, "Runtime.evaluate", {
            "expression": expression,
            "returnByValue": True,
            "awaitPromise": await_promise,
        })
        if result.get("exceptionDetails"):
            exc = result.get("exceptionDetails", {})
            logger.debug(
                "cdp.evaluate: exception %s",
                exc.get("text") or exc.get("exception", {}).get("description", "unknown"),
            )
            return None
        value = result.get("result", {}).get("value")
        return value

    def evaluate_value(self, tab: CdpTab, expression: str, default: Any = None) -> Any:
        value = self.evaluate(tab, expression)
        return default if value is None else value

    def page_state(self, tab: CdpTab) -> dict[str, Any]:
        """Return ``{url, title, selectedText, readyState}`` for a tab."""
        state = self.evaluate(tab, _PAGE_STATE_JS)
        if not isinstance(state, dict):
            state = {}
        state.setdefault("url", tab.url)
        state.setdefault("title", tab.title)
        state.setdefault("selectedText", "")
        state.setdefault("readyState", "unknown")
        return state

    def accessibility_tree(self, tab: CdpTab) -> list[dict[str, Any]]:
        """Return a compact snapshot of the page's accessibility tree."""
        if not tab.ws_url:
            raise CdpError(f"Tab {tab.tab_id} has no WebSocket debugger URL.")
        ws = websocket.create_connection(tab.ws_url, timeout=10.0)
        try:
            _send(ws, "Accessibility.enable", {}, msg_id=1)
            result = _send(ws, "Accessibility.getFullAXTree", {}, msg_id=2)
        finally:
            try:
                ws.close()
            except Exception:
                pass
        nodes = result.get("nodes", [])
        compact: list[dict[str, Any]] = []
        for node in nodes if isinstance(nodes, list) else []:
            if not isinstance(node, dict):
                continue
            compact.append({
                "node_id": node.get("nodeId"),
                "role": _ax_value(node, "role"),
                "name": _ax_value(node, "name"),
                "value": _ax_value(node, "value"),
            })
        return compact

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _ws_call(self, tab: CdpTab, method: str, params: dict[str, Any]) -> dict[str, Any]:
        if not tab.ws_url:
            raise CdpError(f"Tab {tab.tab_id} has no WebSocket debugger URL.")
        ws = websocket.create_connection(tab.ws_url, timeout=10.0)
        try:
            return _send(ws, method, params)
        finally:
            try:
                ws.close()
            except Exception:
                pass


def _ax_value(node: dict[str, Any], key: str) -> Any:
    """Pull a named property value from an AX node."""
    for item in node.get("properties", []):
        if not isinstance(item, dict):
            continue
        if item.get("name") != key:
            continue
        value = item.get("value")
        if isinstance(value, dict):
            return value.get("value")
        return value
    return None


def wait_for(
    client: CdpBrowser,
    predicate,
    timeout: float = 10.0,
    interval: float = 0.4,
) -> Any:
    """Poll *predicate* until truthy or *timeout* elapses.

    ``predicate`` receives the ``CdpBrowser`` and returns a truthy value;
    the first truthy value is returned, otherwise ``None``.
    """
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            value = predicate(client)
        except CdpError:
            value = None
        if value:
            return value
        time.sleep(interval)
    return None
