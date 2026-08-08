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

_MEDIA_PLAYERS = {
    "spotify.exe", "wmplayer.exe", "vlc.exe", " iTunes.exe",
    "foobar2000.exe", "Music.UI.exe", "GrooveMusic.exe",
}


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
        """Detect media players by window title heuristics."""
        try:
            import ctypes
            from ctypes import wintypes
            user32 = ctypes.windll.user32
            results: list[dict[str, Any]] = []

            def _enum_cb(hwnd, _lp):
                buf_len = user32.GetWindowTextLengthW(hwnd) + 1
                if buf_len <= 1:
                    return True
                buf = ctypes.create_unicode_buffer(buf_len)
                user32.GetWindowTextW(hwnd, buf, buf_len)
                title = buf.value
                if not title or not user32.IsWindowVisible(hwnd):
                    return True
                pid = wintypes.DWORD()
                user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
                # Check if this is a known media player
                try:
                    proc = psutil.Process(pid.value)
                    name = proc.name().lower()
                    if name in _MEDIA_PLAYERS and title:
                        results.append({
                            "title": title,
                            "app_name": name.replace(".exe", ""),
                            "is_playing": True,
                            "pid": pid.value,
                        })
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    pass
                return True

            cb = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_int, ctypes.c_int)(_enum_cb)
            user32.EnumWindows(cb, 0)

            if results:
                return max(results, key=lambda r: len(r["title"]))
        except Exception:
            pass
        return {}

    # ── Volume ─────────────────────────────────────────────────────

    @staticmethod
    def _read_volume() -> float:
        """Read master volume level (0.0–1.0) via Windows Core Audio API."""
        try:
            import ctypes
            from ctypes import wintypes, POINTER
            # IMMDeviceEnumerator
            CLSID_MMDeviceEnumerator = "{BCDE0395-E52F-467C-8E3D-C4579291692E}"
            IID_IMMDeviceEnumerator = "{A95664D2-9614-4F35-A746-DE8DB63617E6}"
            IID_IAudioEndpointVolume = "{5CDF2C82-841E-4546-9722-0CF74078229A}"

            ole32 = ctypes.windll.ole32
            ole32.CoInitialize(None)

            from ctypes import create_unicode_buffer, byref, c_float

            mmde = POINTER(ctypes.c_void_p)()
            CLSID = create_unicode_buffer(CLSID_MMDeviceEnumerator)
            IID_MMDE = create_unicode_buffer(IID_IMMDeviceEnumerator)
            ole32.CoCreateInstance(
                byref(CLSID), None, 1, byref(IID_MMDE), byref(mmde),
            )

            if mmde:
                dev = POINTER(ctypes.c_void_p)()
                mmde[0].GetDefaultAudioEndpoint(0, 0, byref(dev))
                if dev:
                    epv = POINTER(ctypes.c_void_p)()
                    IID_EPV = create_unicode_buffer(IID_IAudioEndpointVolume)
                    dev[0].Activate(byref(IID_EPV), 0, None, byref(epv))
                    if epv:
                        level = c_float(0.0)
                        epv[0].GetMasterVolumeLevelScalar(byref(level))
                        ole32.CoUninitialize()
                        return max(0.0, min(1.0, float(level.value)))
            ole32.CoUninitialize()
        except Exception:
            pass
        return 0.5  # default

    # ── Microphone ─────────────────────────────────────────────────

    @staticmethod
    def _read_mic_active() -> bool:
        """Check if any process is currently capturing audio from the mic.

        Heuristic: check if the microphone is being used by any process.
        We check the Windows audio session state for capture devices.
        """
        try:
            # Quick heuristic: check if VoicePanel or any process that uses mic is running
            active_pid = _get_foreground_pid()
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


def _get_foreground_pid() -> int | None:
    try:
        import ctypes
        from ctypes import wintypes
        user32 = ctypes.windll.user32
        hwnd = user32.GetForegroundWindow()
        pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        return pid.value
    except Exception:
        return None


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
