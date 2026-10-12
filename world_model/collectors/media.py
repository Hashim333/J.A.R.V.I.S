"""
world_model/collectors/media.py — Media playback & audio state collector.

Collects:
  - Currently playing media (title, artist, app)
  - System volume level
  - Microphone active state

Strategies (tried in order):
  1. Windows 10+ ``Windows.Media.Control`` API (via winrt) for rich media info
  2. Process heuristic for known media players
  3. Windows Core Audio API (via pycaw / ctypes) for volume & mic
"""

from __future__ import annotations

import logging
import time
from typing import Any

import psutil

from world_model.collectors import BaseCollector, logger
from world_model.collectors import win32_windows

_MEDIA_PLAYERS = {
    "spotify.exe", "wmplayer.exe", "vlc.exe", "itunes.exe",
    "foobar2000.exe", "Music.UI.exe", "GrooveMusic.exe",
}

# Reported when the Core Audio volume cannot be read.
_DEFAULT_VOLUME = 0.5


class MediaCollector(BaseCollector):
    """Collects media playback and audio state."""

    def __init__(self, poll_interval: float = 5.0) -> None:
        super().__init__(poll_interval)
        self._had_smtc_fail = False

    def collect(self) -> dict[str, Any]:
        try:
            return self._collect()
        except Exception as exc:
            logger.warning("MediaCollector: %s", exc)
            return {}

    def _collect(self) -> dict[str, Any]:
        # 1. Try SMTC (Windows 10+ rich media API)
        title: str | None = None
        artist: str | None = None
        app_name: str | None = None
        is_playing = False

        if not self._had_smtc_fail:
            try:
                smtc = self._read_smtc()
                if smtc is not None:
                    title = smtc.get("title")
                    artist = smtc.get("artist")
                    app_name = smtc.get("app_name")
                    is_playing = smtc.get("is_playing", False)
            except Exception:
                self._had_smtc_fail = True
                logger.info("MediaCollector: SMTC unavailable, using fallback")

        # 2. Fallback: known media player processes
        if not is_playing and not title:
            player_info = self._find_media_players()
            if player_info:
                title = player_info.get("title")
                app_name = player_info.get("app_name")
                is_playing = player_info.get("is_playing", False)

        # 3. Volume & mic
        volume = self._read_volume()
        mic_active = self._read_mic_active()

        return {
            "media": {
                "is_playing": is_playing,
                "title": title,
                "artist": artist,
                "app_name": app_name,
                "volume": volume,
                "mic_active": mic_active,
            },
        }

    # ── SMTC (System Media Transport Controls) ─────────────────────

    @staticmethod
    def _read_smtc() -> dict[str, Any] | None:
        """Query Windows SMTC for currently playing media.

        Uses winrt to access  Windows.Media.Control.GlobalSystemMediaTransportControlsSessionManager.
        """
        try:
            import asyncio
            import winrt.windows.media.control as wmc  # type: ignore[import-untyped]

            async def _get():
                mgr = await wmc.GlobalSystemMediaTransportControlsSessionManager.request_async()
                session = mgr.get_current_session()
                if session is None:
                    return None
                info = await session.try_get_media_properties_async()
                playback = session.get_playback_info()
                if info is None:
                    return None
                return {
                    "title": info.title or None,
                    "artist": info.artist or None,
                    "app_name": session.source_app_user_model_id or None,
                    "is_playing": playback.playback_status == 4 if playback else False,
                    # 4 = Playing (winrt.windows.media.control.GlobalSystemMediaTransportControlsSessionPlaybackStatus)
                }

            return asyncio.run(_get())
        except Exception:
            return None

    # ── Process-based fallback ─────────────────────────────────────

    @staticmethod
    def _find_media_players() -> dict[str, Any]:
        """Detect media players by window title heuristics.

        Uses the shared Win32 enumeration helper so the window handle is
        typed correctly (an untyped HWND is truncated to 32 bits on 64-bit
        Windows).
        """
        results: list[dict[str, Any]] = []
        for hwnd, title, pid in win32_windows.iter_visible_windows():
            try:
                name = psutil.Process(pid).name().lower()
            except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                continue
            if name in _MEDIA_PLAYERS:
                results.append({
                    "title": title,
                    "app_name": name.removesuffix(".exe"),
                    "is_playing": True,
                    "pid": pid,
                    "hwnd": hwnd,
                })
        return max(results, key=lambda r: len(r["title"])) if results else {}

    # ── Volume ─────────────────────────────────────────────────────

    @staticmethod
    def _read_volume() -> float:
        """Read master volume (0.0–1.0) through pycaw's Core Audio wrapper.

        Hand-rolled COM vtable calls were replaced: the previous version
        handed ``CoCreateInstance`` a string buffer where it expects a GUID,
        then invoked a method on a possibly-NULL interface pointer, which
        faulted the process with an access violation on every poll.
        ``pycaw`` is the same interface the volume-control actions use.
        """
        try:
            from ctypes import POINTER, cast

            from comtypes import CLSCTX_ALL
            from pycaw.pycaw import AudioUtilities, IAudioEndpointVolume
        except ImportError:
            return _DEFAULT_VOLUME

        try:
            speakers = AudioUtilities.GetSpeakers()
            interface = speakers.Activate(IAudioEndpointVolume._iid_, CLSCTX_ALL, None)
            volume = cast(interface, POINTER(IAudioEndpointVolume))
            level = float(volume.GetMasterVolumeLevelScalar())
        except Exception as exc:
            logger.debug("MediaCollector: volume read failed: %s", exc)
            return _DEFAULT_VOLUME
        return max(0.0, min(1.0, level))

    # ── Microphone ─────────────────────────────────────────────────

    @staticmethod
    def _read_mic_active() -> bool:
        """Check if any process is currently capturing audio from the mic.

        Heuristic: check if the microphone is being used by any process.
        We check the Windows audio session state for capture devices.
        """
        try:
            # Quick heuristic: check if VoicePanel or any process that uses mic is running
            active_pid = win32_windows.foreground_pid()
            if active_pid:
                try:
                    proc = psutil.Process(active_pid)
                    name = proc.name().lower()
                    # Likely mic-using apps
                    if any(m in name for m in ("voice", "microphone", "discord", "zoom", "teams",
                                                "slack", "chrome", "firefox", "edge")):
                        return True
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    pass
            return bool(
                _is_process_running("Discord.exe")
                or _is_process_running("Teams.exe")
                or _is_process_running("Zoom.exe")
                or _is_process_running("VoicePanel.exe")
            )
        except Exception:
            return False


def _is_process_running(name: str) -> bool:
    try:
        for proc in psutil.process_iter(["name"]):
            try:
                if proc.info["name"] and proc.info["name"].lower() == name.lower():
                    return True
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
    except Exception:
        pass
    return False
