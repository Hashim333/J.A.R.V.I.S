"""
automation/youtube.py — YouTube media flow over CDP (DOM / accessibility).

Turns a YouTube search into actual playback and exposes the full state of
the current video.  Everything is driven through the Chrome DevTools
Protocol — DOM queries via ``Runtime.evaluate`` and (where useful) the
accessibility tree.  There is no OCR, no screen-coordinate clicking and no
image matching.

Supported commands:
  - play_first_result(query, index) search + open the Nth *organic* result
  - get_state()                playing/pause/ads/playlist/volume/fullscreen/time
  - get_session()              temporary in-RAM session state (query/title/url)
  - pause / resume
  - play_next / play_previous
  - volume_up / volume_down / mute_video / unmute_video
  - enter_fullscreen / exit_fullscreen
  - replay / go_back
  - skip_ad
  - like_video / subscribe
  - continue_watching
"""

from __future__ import annotations

import logging
import time
from typing import Any

from automation import browser
from automation.browser_service import get_browser_service
from automation.cdp import CdpBrowser, CdpError, CdpTab

logger = logging.getLogger(__name__)


def _client() -> CdpBrowser:
    return get_browser_service().client


def _ok(message: str, **details: object) -> dict:
    result: dict = {"success": True, "status": "success", "message": message}
    if details:
        result["details"] = details
    return result


def _fail(message: str) -> dict:
    return {"success": False, "status": "failed", "message": message}


# ---------------------------------------------------------------------------
# Tab helpers
# ---------------------------------------------------------------------------


def _youtube_tab() -> CdpTab | None:
    for tab in _client().list_tabs():
        if "youtube.com" in tab.url.casefold():
            return tab
    return None


def _results_tab() -> CdpTab | None:
    for tab in _client().list_tabs():
        if "youtube.com/results" in tab.url.casefold():
            return tab
    return None


def _wait_for_watch_page(tab: CdpTab, timeout: float) -> bool:
    deadline = time.monotonic() + timeout
    cdp = _client()
    while time.monotonic() < deadline:
        try:
            state = cdp.page_state(tab)
        except CdpError:
            state = {}
        if "youtube.com/watch" in state.get("url", "").casefold():
            return True
        time.sleep(0.4)
    return False


# ---------------------------------------------------------------------------
# DOM snippets
# ---------------------------------------------------------------------------

# Click the first *organic* (non-sponsored) video result.  Sponsored ads
# live in `ytd-ad-slot-renderer`; organic cards are `ytd-video-renderer`
# (classic layout) or `ytd-rich-item-renderer` (modern layout).  Selecting
# only those renderers makes the "skip sponsored" rule deterministic.
_CLICK_FIRST_ORGANIC_JS = """
(() => {
  const selectors = [
    '#contents ytd-item-section-renderer ytd-video-renderer a#video-title',
    '#contents ytd-video-renderer a#video-title',
    'ytd-rich-item-renderer a#video-title-link',
    'ytd-rich-grid-media a#video-title-link',
  ];
  for (const sel of selectors) {
    const el = document.querySelector(sel);
    if (!el) continue;
    el.scrollIntoView({ block: 'center' });
    el.click();
    return { clicked: true, title: (el.textContent || '').trim() };
  }
  return { clicked: false };
})()
"""

_CLICK_FIRST_LINK_JS = """
(() => {
  const selectors = [
    'ytd-rich-item-renderer a#video-title-link',
    '#contents ytd-video-renderer a#video-title',
    'ytd-compact-video-renderer a#thumbnail',
  ];
  for (const sel of selectors) {
    const el = document.querySelector(sel);
    if (!el) continue;
    el.click();
    return { clicked: true, title: (el.textContent || '').trim() };
  }
  return { clicked: false };
})()
"""

_VIDEO_STATE_JS = """
(() => {
  const video = document.querySelector('video');
  const adOverlay = document.querySelector(
    '.ytp-ad-player-overlay, .ytp-ad-module, .ytp-ad-text-overlay'
  );
  const skipButton = document.querySelector(
    '.ytp-ad-skip-button, .ytp-skip-ad-button, .ytp-ad-skip-button-modern'
  );
  const playlistItems = Array.from(document.querySelectorAll('ytd-playlist-panel-video-renderer'));
  const currentIdx = playlistItems.findIndex((el) => el.classList.contains('current'));
  const playlist = {
    length: playlistItems.length,
    index: currentIdx,
    active: playlistItems.length > 0,
  };
  const isFullscreen = !!(document.fullscreenElement || document.webkitFullscreenElement);
  if (!video) {
    return {
      url: location.href,
      title: document.title || '',
      on_watch_page: /youtube\\.com\\/watch/.test(location.href),
      video: { loaded: false },
      playlist: playlist,
    };
  }
  const adVisible = !!(adOverlay && adOverlay.offsetParent !== null);
  return {
    url: location.href,
    title: document.title || '',
    on_watch_page: /youtube\\.com\\/watch/.test(location.href),
    video: {
      loaded: true,
      playing: !video.paused && !video.ended && !video.seeking && video.readyState > 2,
      paused: video.paused,
      ended: video.ended,
      current_time: video.currentTime || 0,
      duration: video.duration || 0,
      volume: video.volume || 0,
      muted: video.muted,
      playback_rate: video.playbackRate || 1,
      fullscreen: isFullscreen,
      ad_present: !!adVisible,
      ad_skippable: !!(skipButton && skipButton.offsetParent !== null),
    },
    playlist: playlist,
  };
})()
"""

_PAUSE_JS = """
(() => {
  const v = document.querySelector('video');
  if (!v) return { ok: false };
  if (!v.paused) v.pause();
  return { ok: true, paused: v.paused };
})()
"""

_RESUME_JS = """
(() => {
  const v = document.querySelector('video');
  if (!v) return { ok: false };
  if (v.paused) { v.play().catch(() => {}); }
  return { ok: true, paused: v.paused };
})()
"""

_NEXT_JS = """
(() => {
  const playerNext = document.querySelector('.ytp-next-button');
  if (playerNext) { playerNext.click(); return { ok: true }; }
  const items = document.querySelectorAll(
    'ytd-playlist-panel-video-renderer:not(.current) a#thumbnail'
  );
  if (items[0]) { items[0].click(); return { ok: true }; }
  const upNext = document.querySelector(
    'ytd-compact-video-renderer a#thumbnail, ytd-compact-autoplay-renderer a#thumbnail, .ytp-autonav-endscreen-upnext a#thumbnail'
  );
  if (upNext) { upNext.click(); return { ok: true }; }
  return { ok: false };
})()
"""

_PREVIOUS_JS = """
(() => {
  const playerPrev = document.querySelector('.ytp-prev-button');
  if (playerPrev) { playerPrev.click(); return { ok: true }; }
  const items = Array.from(document.querySelectorAll('ytd-playlist-panel-video-renderer'));
  const idx = items.findIndex((el) => el.classList.contains('current'));
  const prev = idx > 0 ? items[idx - 1] : null;
  const link = prev ? prev.querySelector('a#thumbnail') : null;
  if (link) { link.click(); return { ok: true }; }
  return { ok: false };
})()
"""

_SKIP_AD_JS = """
(() => {
  const selectors = [
    '.ytp-ad-skip-button',
    '.ytp-skip-ad-button',
    '.ytp-ad-skip-button-modern',
    '.ytp-ad-skip-button-slot button',
  ];
  for (const sel of selectors) {
    const btn = document.querySelector(sel);
    if (btn) { btn.click(); return { ok: true }; }
  }
  return { ok: false };
})()
"""

_LIKE_JS = """
(() => {
  const selectors = [
    'ytd-segmented-like-dislike-button-renderer button[id="like-button"]',
    'ytd-toggle-button-renderer.is-icon-button button[aria-pressed]',
    'button[aria-pressed][aria-label^="like" i]',
    '#top-level-buttons-computed button[aria-pressed][aria-label*="like" i]',
  ];
  for (const sel of selectors) {
    const btn = document.querySelector(sel);
    if (!btn) continue;
    const pressed = btn.getAttribute('aria-pressed');
    if (pressed === 'true') return { ok: true, already_liked: true };
    btn.click();
    return { ok: true, already_liked: false };
  }
  return { ok: false };
})()
"""

_SUBSCRIBE_JS = """
(() => {
  const selectors = [
    'ytd-subscribe-button-renderer button[aria-label*="subscribe" i]',
    'ytd-subscribe-button-renderer tp-yt-paper-button[aria-label*="subscribe" i]',
    '#subscribe-button button[aria-label*="subscribe" i]',
    'ytd-button-renderer[is-icon-button] #button[aria-label*="subscribe" i]',
  ];
  for (const sel of selectors) {
    const btn = document.querySelector(sel);
    if (!btn) continue;
    const label = (btn.getAttribute('aria-label') || '').toLowerCase();
    if (label.includes('subscribed') && !label.includes('subscribe to')) {
      return { ok: true, already_subscribed: true };
    }
    btn.click();
    return { ok: true, already_subscribed: false };
  }
  return { ok: false };
})()
"""

# Click the Nth *organic* (non-sponsored, deduplicated) video result,
# 1-based.  Generalises the "first result" rule so "play the second one"
# works against the same open results page.
_CLICK_RESULT_JS_TEMPLATE = """
((n) => {
  const selectors = [
    '#contents ytd-item-section-renderer ytd-video-renderer a#video-title',
    '#contents ytd-video-renderer a#video-title',
    'ytd-rich-item-renderer a#video-title-link',
    'ytd-rich-grid-media a#video-title-link',
  ];
  const seen = new Set();
  const organic = [];
  for (const sel of selectors) {
    for (const el of document.querySelectorAll(sel)) {
      const href = el.href || '';
      if (href && seen.has(href)) continue;
      seen.add(href);
      organic.push(el);
    }
  }
  const el = organic[n - 1];
  if (!el) return { clicked: false, count: organic.length };
  el.scrollIntoView({ block: 'center' });
  el.click();
  return { clicked: true, title: (el.textContent || '').trim(), index: n };
})(%d)
"""

_VOLUME_STEP_JS_TEMPLATE = """
((delta) => {
  const v = document.querySelector('video');
  if (!v) return { ok: false };
  if (v.muted && delta > 0) v.muted = false;
  v.volume = Math.min(1, Math.max(0, (v.volume || 0) + delta));
  return { ok: true, volume: Math.round(v.volume * 100), muted: v.muted };
})(%s)
"""

_MUTE_JS = """
(() => {
  const v = document.querySelector('video');
  if (!v) return { ok: false };
  v.muted = true;
  return { ok: true, muted: true };
})()
"""

_UNMUTE_JS = """
(() => {
  const v = document.querySelector('video');
  if (!v) return { ok: false };
  v.muted = false;
  return { ok: true, muted: false };
})()
"""

_ENTER_FULLSCREEN_JS = """
(() => {
  if (document.fullscreenElement || document.webkitFullscreenElement) {
    return { ok: true, fullscreen: true, already: true };
  }
  const player = document.querySelector('#movie_player')
    || document.querySelector('.html5-video-player')
    || document.querySelector('video');
  if (!player) return { ok: false };
  const req = player.requestFullscreen || player.webkitRequestFullscreen
    || player.requestFullScreen || player.webkitRequestFullScreen;
  if (!req) return { ok: false };
  try { req.call(player); } catch (e) { return { ok: false }; }
  return { ok: true, fullscreen: true };
})()
"""

_EXIT_FULLSCREEN_JS = """
(() => {
  if (!(document.fullscreenElement || document.webkitFullscreenElement)) {
    return { ok: true, fullscreen: false, already: true };
  }
  const exit = document.exitFullscreen || document.webkitExitFullscreen;
  if (!exit) return { ok: false };
  try { exit.call(document); } catch (e) { return { ok: false }; }
  return { ok: true, fullscreen: false };
})()
"""

_REPLAY_JS = """
(() => {
  const v = document.querySelector('video');
  if (!v) return { ok: false };
  v.currentTime = 0;
  v.play().catch(() => {});
  return { ok: true };
})()
"""

_GO_BACK_JS = """
(() => { history.back(); return { ok: true }; })()
"""

# Minimal temporary YouTube session state (in-RAM only; cleared when the
# process exits).  Lets contextual follow-ups report what is playing even
# before the next CDP poll.
_SESSION: dict[str, Any] = {
    "active": False,
    "last_query": "",
    "last_title": "",
    "last_url": "",
}


def get_session() -> dict[str, Any]:
    """Return a copy of the temporary YouTube session state."""
    return dict(_SESSION)


def _note_session(title: str = "", url: str = "", query: str | None = None) -> None:
    if query is not None:
        _SESSION["last_query"] = query
    if title:
        _SESSION["last_title"] = title
    if url:
        _SESSION["last_url"] = url
    _SESSION["active"] = True


# ---------------------------------------------------------------------------
# Play flow
# ---------------------------------------------------------------------------


def play_first_result(query: str, timeout: float = 12.0, index: int = 1) -> dict[str, Any]:
    """Search YouTube and open the Nth (default first) non-sponsored video
    result.

    Returns a handler-style result dict consumed by
    ``ActionResult.from_handler``.  When *query* is empty the current
    YouTube results page is used instead of searching again, so "play the
    second one" after a search reuses the open results tab.
    """
    query = (query or "").strip()
    index = max(1, int(index or 1))
    try:
        cdp = _client()
    except Exception as exc:
        return _fail(f"Browser automation unavailable ({exc}).")

    try:
        if query:
            search_result = browser.search("youtube", query)
            if not search_result.get("success"):
                return {
                    "success": False,
                    "status": "failed",
                    "message": search_result.get(
                        "message", "The YouTube search failed."
                    ),
                }
        tab = _results_tab()
        if tab is None:
            return {
                "success": False,
                "status": "failed",
                "message": (
                    "No YouTube results page is open. "
                    "Say 'play <song>' to search first."
                ),
            }
        cdp.activate(tab)
    except CdpError as exc:
        return _fail(f"Browser automation failed ({exc}).")

    try:
        clicked = cdp.evaluate(tab, _CLICK_RESULT_JS_TEMPLATE % index)
    except CdpError as exc:
        return _fail(f"Could not click result #{index} ({exc}).")

    if not (isinstance(clicked, dict) and clicked.get("clicked")):
        found = clicked.get("count", 0) if isinstance(clicked, dict) else 0
        message = (
            f"I only found {found} result(s); there is no result #{index}."
            if isinstance(clicked, dict) and found
            else "The results loaded but I couldn't find a video to open."
        )
        return {
            "success": False,
            "status": "retrying",
            "message": message,
        }

    if not _wait_for_watch_page(tab, timeout):
        _note_session(query=query)
        return {
            "success": False,
            "status": "waiting",
            "message": f"The video for {query!r} is loading; I couldn't confirm playback yet.",
        }

    title = (clicked.get("title") or query or "the video")
    _note_session(title=str(title), url=getattr(tab, "url", ""), query=query)
    ordinal = "" if index == 1 else f" #{index}"
    return _ok(
        (
            f"Now playing the{ordinal} result for {query!r} on YouTube."
            if query
            else f"Now playing {title!r} on YouTube."
        ),
        title=title,
    )


# ---------------------------------------------------------------------------
# State
# ---------------------------------------------------------------------------


def get_state() -> dict[str, Any]:
    """Return the full YouTube playback state of the open YouTube tab."""
    try:
        cdp = _client()
    except Exception as exc:
        return _fail(f"Browser automation unavailable ({exc}).")
    try:
        tab = _youtube_tab()
        if tab is None:
            return _fail("No YouTube tab is open.")
        cdp.activate(tab)
        raw = cdp.evaluate(tab, _VIDEO_STATE_JS)
    except CdpError as exc:
        return _fail(f"Could not read the YouTube tab ({exc}).")

    if raw is None:
        raw = {}
    video = raw.get("video") if isinstance(raw, dict) and isinstance(raw.get("video"), dict) else {}
    details: dict[str, Any] = {
        "tab": tab.tab_id,
        "url": raw.get("url", tab.url),
        "title": raw.get("title", tab.title),
        "on_watch_page": bool(raw.get("on_watch_page", False)),
        "video_loaded": bool(video.get("loaded", False)),
        "playing": bool(video.get("playing", False)),
        "paused": bool(video.get("paused", False)),
        "current_time": video.get("current_time", 0.0),
        "duration": video.get("duration", 0.0),
        "volume": video.get("volume", 0.0),
        "muted": bool(video.get("muted", False)),
        "playback_rate": video.get("playback_rate", 1.0),
        "fullscreen": bool(video.get("fullscreen", False)),
        "ad_present": bool(video.get("ad_present", False)),
        "ad_skippable": bool(video.get("ad_skippable", False)),
        "playlist": video.get("playlist", {}),
    }
    _note_session(
        title=str(raw.get("title", "") or tab.title or ""),
        url=str(raw.get("url", "") or tab.url or ""),
    )
    return _ok("YouTube state.", **details)


# ---------------------------------------------------------------------------
# Video controls
# ---------------------------------------------------------------------------


def _run_on_video(js: str, success_message: str, missing_message: str) -> dict[str, Any]:
    try:
        cdp = _client()
    except Exception as exc:
        return _fail(f"Browser automation unavailable ({exc}).")
    try:
        tab = _youtube_tab()
        if tab is None:
            return _fail("No YouTube tab is open.")
        cdp.activate(tab)
        result = cdp.evaluate(tab, js)
    except CdpError as exc:
        return _fail(f"Browser automation failed ({exc}).")
    if not isinstance(result, dict):
        return _fail("YouTube did not respond to the command.")
    if result.get("ok") is False:
        return {"success": False, "status": "retrying", "message": missing_message}
    return _ok(success_message, **{k: v for k, v in result.items() if k != "ok"})


def pause() -> dict[str, Any]:
    return _run_on_video(_PAUSE_JS, "Paused the video.", "There is no video playing to pause.")


def resume() -> dict[str, Any]:
    return _run_on_video(_RESUME_JS, "Resumed the video.", "There is no video to resume.")


def play_next() -> dict[str, Any]:
    return _run_on_video(_NEXT_JS, "Skipped to the next video.", "There is no next video.")


def play_previous() -> dict[str, Any]:
    return _run_on_video(_PREVIOUS_JS, "Went to the previous video.", "There is no previous video.")


def skip_ad() -> dict[str, Any]:
    return _run_on_video(_SKIP_AD_JS, "Skipped the ad.", "There is no skippable ad right now.")


def like_video() -> dict[str, Any]:
    result = _run_on_video(_LIKE_JS, "Liked the video.", "Could not find the like button.")
    if result.get("success") and result.get("details", {}).get("already_liked"):
        result["message"] = "You already liked this video."
    return result


def subscribe() -> dict[str, Any]:
    result = _run_on_video(_SUBSCRIBE_JS, "Subscribed to the channel.", "Could not find the subscribe button.")
    if result.get("success") and result.get("details", {}).get("already_subscribed"):
        result["message"] = "You are already subscribed to this channel."
    return result


# ---------------------------------------------------------------------------
# Player volume / display controls
# ---------------------------------------------------------------------------


def _volume_step(delta: float) -> dict[str, Any]:
    """Step the YouTube player volume; falls back to the system volume when
    no YouTube tab is open so the command still has an audible effect."""
    result = _run_on_video(
        _VOLUME_STEP_JS_TEMPLATE % delta,
        "Turned the volume up." if delta > 0 else "Turned the volume down.",
        "There is no video to adjust the volume of.",
    )
    if not result.get("success") and "No YouTube tab" in str(result.get("message", "")):
        from automation import apps as system_apps

        return (
            system_apps.increase_volume(10) if delta > 0
            else system_apps.decrease_volume(10)
        )
    return result


def volume_up() -> dict[str, Any]:
    return _volume_step(+0.1)


def volume_down() -> dict[str, Any]:
    return _volume_step(-0.1)


def mute_video() -> dict[str, Any]:
    result = _run_on_video(_MUTE_JS, "Muted the video.", "There is no video to mute.")
    if not result.get("success") and "No YouTube tab" in str(result.get("message", "")):
        from automation import apps as system_apps

        return system_apps.mute_volume()
    return result


def unmute_video() -> dict[str, Any]:
    result = _run_on_video(_UNMUTE_JS, "Unmuted the video.", "There is no video to unmute.")
    if not result.get("success") and "No YouTube tab" in str(result.get("message", "")):
        from automation import apps as system_apps

        return system_apps.unmute_volume()
    return result


def enter_fullscreen() -> dict[str, Any]:
    result = _run_on_video(
        _ENTER_FULLSCREEN_JS, "Went fullscreen.", "Could not find the video player."
    )
    if result.get("success") and result.get("details", {}).get("already"):
        result["message"] = "Already in fullscreen."
    return result


def exit_fullscreen() -> dict[str, Any]:
    result = _run_on_video(
        _EXIT_FULLSCREEN_JS, "Exited fullscreen.", "Could not exit fullscreen."
    )
    if result.get("success") and result.get("details", {}).get("already"):
        result["message"] = "Not in fullscreen."
    return result


def replay() -> dict[str, Any]:
    return _run_on_video(_REPLAY_JS, "Replaying from the start.", "There is no video to replay.")


def go_back() -> dict[str, Any]:
    try:
        cdp = _client()
    except Exception as exc:
        return _fail(f"Browser automation unavailable ({exc}).")
    try:
        tab = _youtube_tab()
        if tab is None:
            return _fail("No YouTube tab is open.")
        cdp.activate(tab)
        cdp.evaluate(tab, _GO_BACK_JS)
    except CdpError as exc:
        return _fail(f"Browser automation failed ({exc}).")
    return _ok("Went back.")


def continue_watching() -> dict[str, Any]:
    """Resume the current video, or open the first available video link."""
    try:
        cdp = _client()
    except Exception as exc:
        return _fail(f"Browser automation unavailable ({exc}).")
    try:
        tab = _youtube_tab()
        if tab is None:
            return _fail("No YouTube tab is open.")
        cdp.activate(tab)
        raw = cdp.evaluate(tab, _VIDEO_STATE_JS)
    except CdpError as exc:
        return _fail(f"Browser automation failed ({exc}).")

    video = raw.get("video") if isinstance(raw, dict) and isinstance(raw.get("video"), dict) else {}
    if video.get("loaded") and video.get("playing"):
        return _ok("The video is already playing.")
    if video.get("loaded") and video.get("paused"):
        return resume()

    try:
        clicked = cdp.evaluate(tab, _CLICK_FIRST_LINK_JS)
    except CdpError as exc:
        return _fail(f"Could not find something to continue ({exc}).")
    if not (isinstance(clicked, dict) and clicked.get("clicked")):
        return {
            "success": False,
            "status": "retrying",
            "message": "I couldn't find something to continue watching.",
        }
    if not _wait_for_watch_page(tab, 12.0):
        return {
            "success": False,
            "status": "waiting",
            "message": "The video is loading; I couldn't confirm playback yet.",
        }
    return _ok("Continuing where you left off.")
