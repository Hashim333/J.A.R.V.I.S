"""
world_model/collectors/win32_shell.py — Safe Win32 shell / COM helpers.

Explorer window paths, ``.lnk`` targets and the Recent Items folder all need
COM or a typed shell32 call.  The inline implementations this replaces
initialised *and* uninitialised COM around every single lookup, and used an
untyped ``GetWindowThreadProcessId`` (a truncated 64-bit window handle on
x64).  Here COM is initialised once per thread and each dispatch is cached,
so a poll costs a lookup rather than an apartment startup.
"""

from __future__ import annotations

import logging
import os
import threading
from ctypes import c_int, c_long, create_unicode_buffer
from ctypes import wintypes

from world_model.collectors import win32_windows

logger = logging.getLogger(__name__)

# CSIDL_RECENT: the per-user "Recent Items" folder.
_CSIDL_RECENT = 0x0008
_SHGFP_TYPE_CURRENT = 0x0000
_MAX_PATH = 260

# COM apartments are per-thread, so the initialisation flag and the cached
# dispatches must be thread-local.
_local = threading.local()
_shell32 = None


def _get_shell32():
    """Return shell32 with explicit signatures, or ``None``."""
    global _shell32
    if _shell32 is not None:
        return _shell32
    try:
        from ctypes import WinDLL

        shell32 = WinDLL("shell32", use_last_error=True)
        shell32.SHGetFolderPathW.argtypes = [
            wintypes.HWND, c_int, wintypes.HANDLE, wintypes.DWORD,
            wintypes.LPWSTR,
        ]
        shell32.SHGetFolderPathW.restype = c_long  # HRESULT
    except Exception as exc:
        logger.warning("shell32 unavailable: %s", exc)
        return None
    _shell32 = shell32
    return shell32


def _ensure_com() -> bool:
    """Initialise COM once for the calling thread."""
    if getattr(_local, "com_ready", False):
        return True
    try:
        import pythoncom

        pythoncom.CoInitialize()
    except Exception as exc:
        logger.debug("COM unavailable: %s", exc)
        return False
    _local.com_ready = True
    return True


def _dispatch(prog_id: str):
    """Return a cached COM dispatch for *prog_id* on this thread."""
    if not _ensure_com():
        return None
    cache = getattr(_local, "dispatches", None)
    if cache is None:
        cache = {}
        _local.dispatches = cache
    existing = cache.get(prog_id)
    if existing is not None:
        return existing
    try:
        from win32com.client import Dispatch

        created = Dispatch(prog_id)
    except Exception as exc:
        logger.debug("COM dispatch %r unavailable: %s", prog_id, exc)
        return None
    cache[prog_id] = created
    return created


def recent_items_folder() -> str | None:
    """Path of the per-user Recent Items folder, or ``None``."""
    shell32 = _get_shell32()
    if shell32 is None:
        return None
    try:
        buffer = create_unicode_buffer(_MAX_PATH)
        hresult = shell32.SHGetFolderPathW(
            None, _CSIDL_RECENT, None, _SHGFP_TYPE_CURRENT, buffer,
        )
        if int(hresult) != 0:
            return None
        path = buffer.value
    except Exception as exc:
        logger.debug("Recent Items lookup failed: %s", exc)
        return None
    return path if os.path.isdir(path) else None


def explorer_folder_for_pid(pid: int) -> str | None:
    """Current folder of the Explorer window owned by *pid*, or ``None``."""
    if not pid:
        return None
    shell = _dispatch("Shell.Application")
    if shell is None:
        return None
    try:
        windows = shell.Windows()
    except Exception as exc:
        logger.debug("Shell.Windows() failed: %s", exc)
        return None
    for window in windows:
        try:
            if win32_windows.window_pid(int(window.HWND)) != pid:
                continue
            path = window.Document.Folder.Self.Path
        except Exception as exc:
            logger.debug("Explorer window probe failed: %s", exc)
            continue
        if path and os.path.isdir(path):
            return str(path)
    return None


def resolve_shortcut(path: str) -> str | None:
    """Resolve a ``.lnk`` shortcut to its existing target, or ``None``."""
    shell = _dispatch("WScript.Shell")
    if shell is None:
        return None
    try:
        target = shell.CreateShortCut(path).TargetPath
    except Exception as exc:
        logger.debug("Could not resolve %s: %s", path, exc)
        return None
    return str(target) if target and os.path.isfile(target) else None
