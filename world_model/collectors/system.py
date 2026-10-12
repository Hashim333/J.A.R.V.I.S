"""
world_model/collectors/system.py — System resource collector.

Collects:
  - CPU usage %
  - RAM usage %
  - GPU usage % (NVML → WMI fallback)
  - Battery level & charging status
  - Network connectivity
  - Clipboard text

All I/O runs on a background thread — never on the UI thread.
"""

from __future__ import annotations

import ctypes
import logging
import time
from typing import Any

import psutil

from world_model.collectors import BaseCollector, logger


class SystemCollector(BaseCollector):
    """Collects system resource information."""

    def __init__(self, poll_interval: float = 5.0) -> None:
        super().__init__(poll_interval)
        # GPU state (lazy-initialised on background thread)
        self._has_nvml = False
        self._nvml_handle = None
        self._has_wmi_gpu = False
        self._wmi_client = None
        self._wmi_initialised = False

    def collect(self) -> dict[str, Any]:
        try:
            return self._collect()
        except Exception as exc:
            logger.warning("SystemCollector: %s", exc)
            return {}

    def _collect(self) -> dict[str, Any]:
        cpu = self._read_cpu()
        ram = self._read_ram()
        gpu = self._read_gpu()
        battery = self._read_battery()
        network = self._read_network()
        clipboard = self._read_clipboard()

        return {
            "system": {
                "cpu_percent": cpu,
                "ram_percent": ram,
                "gpu_percent": gpu,
                "battery_percent": battery["percent"],
                "battery_charging": battery["charging"],
                "network_connected": network,
                "clipboard_text": clipboard,
            },
        }

    # ── Individual readers ─────────────────────────────────────────

    @staticmethod
    def _read_cpu() -> float:
        try:
            return psutil.cpu_percent(interval=0)
        except Exception:
            return 0.0

    @staticmethod
    def _read_ram() -> float:
        try:
            return psutil.virtual_memory().percent
        except Exception:
            return 0.0

    def _read_gpu(self) -> float:
        self._init_gpu_once()
        if self._has_nvml:
            try:
                import pynvml  # type: ignore[import-untyped] # noqa: F811
                if self._nvml_handle is not None:
                    return float(pynvml.nvmlDeviceGetUtilizationRates(self._nvml_handle).gpu)
            except Exception:
                pass
        if self._has_wmi_gpu and self._wmi_client is not None:
            try:
                total = 0
                for e in self._wmi_client.Win32_PerfFormattedData_GPUPerformanceCounters_GPUEngine():
                    if 'engtype_3D' in e.Name:
                        v = e.UtilizationPercentage
                        if v is not None:
                            total += int(v)
                return min(float(total), 100.0)
            except Exception:
                pass
        return 0.0

    def _init_gpu_once(self) -> None:
        if self._wmi_initialised:
            return
        self._wmi_initialised = True

        # NVML
        try:
            import pynvml  # type: ignore[import-untyped]
            pynvml.nvmlInit()
            self._nvml_handle = pynvml.nvmlDeviceGetHandleByIndex(0)
            self._has_nvml = True
            logger.info("SystemCollector: NVML GPU monitoring initialized")
        except Exception:
            pass

        # WMI fallback
        if not self._has_nvml:
            try:
                import pythoncom  # type: ignore[import-untyped]
                import wmi  # type: ignore[import-untyped]
                pythoncom.CoInitialize()
                self._wmi_client = wmi.WMI()
                test = self._wmi_client.Win32_PerfFormattedData_GPUPerformanceCounters_GPUEngine()
                if test:
                    self._has_wmi_gpu = True
                    logger.info("SystemCollector: WMI GPU monitoring initialized")
            except Exception:
                self._wmi_client = None

    @staticmethod
    def _read_battery() -> dict[str, Any]:
        try:
            batt = psutil.sensors_battery()
            if batt is not None:
                return {"percent": float(batt.percent), "charging": bool(batt.power_plugged)}
        except Exception:
            pass
        return {"percent": -1.0, "charging": False}

    @staticmethod
    def _read_network() -> bool:
        """Check whether any network interface is up and has an IP."""
        try:
            addrs = psutil.net_if_addrs()
            stats = psutil.net_if_stats()
            for iface, s in stats.items():
                if s.isup and iface in addrs:
                    for addr in addrs[iface]:
                        if addr.family == 2 and addr.address:  # AF_INET
                            return True
        except Exception:
            pass
        return False

    @staticmethod
    def _read_clipboard() -> str:
        """Read plain text from the Windows clipboard ("" when unavailable)."""
        return read_clipboard_text()


# ── Clipboard helpers ───────────────────────────────────────────────
#
# Declared once at module level so the Win32 signatures are applied a single
# time instead of on every poll.

_CF_UNICODETEXT = 13
_CLIPBOARD_OPEN_RETRIES = 3
_CLIPBOARD_RETRY_SECONDS = 0.05
_clipboard_api: tuple[Any, Any] | None = None


def _get_clipboard_api() -> tuple[Any, Any] | None:
    """Return ``(user32, kernel32)`` with explicit Win32 signatures.

    The signatures are the fix, not decoration: ctypes defaults an untyped
    integer argument to C ``int``, so a 64-bit HGLOBAL was truncated to 32
    bits.  ``GlobalSize`` / ``GlobalLock`` then dereferenced a wild pointer
    and the following ``memmove`` faulted the process (observed as a Windows
    fatal exception / access violation).
    """
    global _clipboard_api
    if _clipboard_api is not None:
        return _clipboard_api
    try:
        from ctypes import WinDLL, c_size_t
        from ctypes import wintypes

        user32 = WinDLL("user32", use_last_error=True)
        kernel32 = WinDLL("kernel32", use_last_error=True)

        user32.OpenClipboard.argtypes = [wintypes.HWND]
        user32.OpenClipboard.restype = wintypes.BOOL
        user32.CloseClipboard.argtypes = []
        user32.CloseClipboard.restype = wintypes.BOOL
        user32.GetClipboardData.argtypes = [wintypes.UINT]
        user32.GetClipboardData.restype = wintypes.HANDLE

        kernel32.GlobalSize.argtypes = [wintypes.HGLOBAL]
        kernel32.GlobalSize.restype = c_size_t
        kernel32.GlobalLock.argtypes = [wintypes.HGLOBAL]
        kernel32.GlobalLock.restype = wintypes.LPVOID
        kernel32.GlobalUnlock.argtypes = [wintypes.HGLOBAL]
        kernel32.GlobalUnlock.restype = wintypes.BOOL
    except Exception as exc:
        logger.warning("Clipboard API unavailable: %s", exc)
        return None
    _clipboard_api = (user32, kernel32)
    return _clipboard_api


def _open_clipboard(user32: Any) -> bool:
    """Open the clipboard, retrying briefly while another process holds it."""
    for _ in range(_CLIPBOARD_OPEN_RETRIES):
        if user32.OpenClipboard(None):
            return True
        time.sleep(_CLIPBOARD_RETRY_SECONDS)
    return False


def read_clipboard_text() -> str:
    """Read CF_UNICODETEXT, returning "" when the clipboard holds no text."""
    api = _get_clipboard_api()
    if api is None:
        return ""
    user32, kernel32 = api
    if not _open_clipboard(user32):
        return ""
    try:
        handle = user32.GetClipboardData(_CF_UNICODETEXT)
        if not handle:
            return ""
        size = int(kernel32.GlobalSize(handle))
        if size < 2:
            return ""
        locked = kernel32.GlobalLock(handle)
        if not locked:
            return ""
        try:
            buffer = (ctypes.c_char * size)()
            ctypes.memmove(buffer, locked, size)
            # CF_UNICODETEXT is UTF-16-LE terminated by one NUL code unit.
            return bytes(buffer).decode("utf-16-le", errors="replace").rstrip("\x00")
        finally:
            kernel32.GlobalUnlock(handle)
    except Exception as exc:
        logger.debug("Clipboard read failed: %s", exc)
        return ""
    finally:
        user32.CloseClipboard()
