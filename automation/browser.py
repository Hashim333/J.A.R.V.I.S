"""
automation/browser.py

Default-browser URL launcher.

This module does not automate browser internals. It only asks the
operating system to open a URL in the user's default browser.
"""

from __future__ import annotations

import webbrowser
from urllib.parse import quote_plus


class BrowserOperationError(Exception):
    """Raised when browser URL launch fails."""


_KNOWN_URLS: dict[str, str] = {
    "google": "https://www.google.com",
    "youtube": "https://www.youtube.com",
    "github": "https://github.com",
    "chatgpt": "https://chatgpt.com",
    "gmail": "https://mail.google.com",
}

_SEARCH_URLS: dict[str, str] = {
    "google": "https://www.google.com/search?q={query}",
    "youtube": "https://www.youtube.com/results?search_query={query}",
    "github": "https://github.com/search?q={query}",
}


def open_url(url: str) -> bool:
    """Open a URL or known website name in the default browser."""
    normalized_url = _normalize_url(url)

    try:
        opened = webbrowser.open(normalized_url, new=2, autoraise=True)
    except Exception as exc:
        raise BrowserOperationError(
            f"Failed to open URL {normalized_url!r}: {exc}"
        ) from exc

    if not opened:
        raise BrowserOperationError(f"Default browser refused URL {normalized_url!r}.")

    return True


def search(provider: str, query: str) -> bool:
    """Open a provider search URL in the default browser."""
    provider_key = provider.strip().casefold()
    template = _SEARCH_URLS.get(provider_key)
    if template is None:
        raise BrowserOperationError(f"Unsupported search provider: {provider!r}.")

    if not isinstance(query, str) or not query.strip():
        raise BrowserOperationError("Search query must be a non-empty string.")

    return open_url(template.format(query=quote_plus(query.strip())))


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
