"""
system_awareness/collectors/devices.py — hardware device collectors.

Collects USB devices, printers, camera, Bluetooth and display configuration.
All use WMI (or ctypes) guarded behind try/except so a missing component
degrades to an empty result instead of a crash.
"""

from __future__ import annotations

import logging
import time
from typing import Any

from world_model.collectors import BaseCollector, logger

_WMI = None


def _wmi():
    global _WMI
    if _WMI is not None:
        return _WMI
    try:
        import pythoncom  # type: ignore[import-untyped]
        import wmi  # type: ignore[import-untyped]
        pythoncom.CoInitialize()
        _WMI = wmi.WMI()
    except Exception:
        _WMI = False
    return _WMI if _WMI else None


class UsbCollector(BaseCollector):
    """Collects USB devices via WMI PnP entities."""

    def __init__(self, poll_interval: float = 30.0) -> None:
        super().__init__(poll_interval)

    def collect(self) -> dict[str, Any]:
        try:
            return self._collect()
        except Exception as exc:
            logger.warning("UsbCollector: %s", exc)
            return {}

    def _collect(self) -> dict[str, Any]:
        client = _wmi()
        if client is None:
            return {"usb_devices": []}
        devices = []
        for ent in client.Win32_PnPEntity(PNPClass="USB"):
            name = ent.Name
            if not name:
                continue
            devices.append({"name": str(name), "status": str(getattr(ent, "Status", "") or "")})
        return {"usb_devices": devices}


class PrinterCollector(BaseCollector):
    """Collects installed printers via WMI."""

    def __init__(self, poll_interval: float = 30.0) -> None:
        super().__init__(poll_interval)

    def collect(self) -> dict[str, Any]:
        try:
            return self._collect()
        except Exception as exc:
            logger.warning("PrinterCollector: %s", exc)
            return {}

    def _collect(self) -> dict[str, Any]:
        client = _wmi()
        if client is None:
            return {"printers": []}
        printers = []
        for pr in client.Win32_Printer():
            printers.append({
                "name": str(pr.Name or ""),
                "is_default": bool(getattr(pr, "Default", False)),
                "is_online": not bool(getattr(pr, "WorkOffline", False)),
                "status": str(getattr(pr, "PrinterStatus", 0) or 0),
            })
        return {"printers": printers}


class CameraCollector(BaseCollector):
    """Collects camera presence and in-use state.

    Presence via WMI PnP entities (Camera/Image classes); in-use is a
    best-effort heuristic based on camera-consuming processes running.
    """

    def __init__(self, poll_interval: float = 10.0) -> None:
        super().__init__(poll_interval)

    def collect(self) -> dict[str, Any]:
        try:
            return self._collect()
        except Exception as exc:
            logger.warning("CameraCollector: %s", exc)
            return {}

    def _collect(self) -> dict[str, Any]:
        import psutil

        devices = []
        client = _wmi()
        if client is not None:
            try:
                for ent in client.Win32_PnPEntity():
                    pnp_class = str(getattr(ent, "PNPClass", "") or "")
                    if pnp_class in ("Camera", "Image"):
                        if ent.Name:
                            devices.append(str(ent.Name))
            except Exception:
                pass

        in_use = False
        cam_apps = ("zoom", "teams", "skype", "camera", "slack", "webex", "obs")
        for proc in psutil.process_iter(["name"]):
            try:
                name = (proc.info.get("name") or "").lower()
                if any(c in name for c in cam_apps):
                    in_use = True
                    break
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue

        return {"camera": {"present": bool(devices), "in_use": in_use, "devices": devices}}


class BluetoothCollector(BaseCollector):
    """Collects Bluetooth adapter state and paired/connected devices."""

    def __init__(self, poll_interval: float = 30.0) -> None:
        super().__init__(poll_interval)

    def collect(self) -> dict[str, Any]:
        try:
            return self._collect()
        except Exception as exc:
            logger.warning("BluetoothCollector: %s", exc)
            return {}

    def _collect(self) -> dict[str, Any]:
        client = _wmi()
        if client is None:
            return {"bluetooth": None}
        enabled = False
        devices = []
        for ent in client.Win32_PnPEntity():
            pnp_class = str(getattr(ent, "PNPClass", "") or "")
            name = str(ent.Name or "")
            if pnp_class in ("Bluetooth", "BluetoothLE"):
                if "adapter" in name.casefold() or "bluetooth device" in name.casefold():
                    continue
                status = str(getattr(ent, "Status", "") or "")
                if name and status:
                    devices.append(name)
                if pnp_class == "Bluetooth" and "radio" in name.casefold():
                    enabled = status in ("OK", "Degraded")
        return {"bluetooth": {"enabled": enabled, "devices": devices}}


class DisplayCollector(BaseCollector):
    """Collects display configuration via EnumDisplayMonitors/Settings."""

    def __init__(self, poll_interval: float = 30.0) -> None:
        super().__init__(poll_interval)

    def collect(self) -> dict[str, Any]:
        try:
            return self._collect()
        except Exception as exc:
            logger.warning("DisplayCollector: %s", exc)
            return {}

    def _collect(self) -> dict[str, Any]:
        import ctypes
        from ctypes import wintypes

        user32 = ctypes.windll.user32
        displays: list[dict[str, Any]] = []

        class _RECT(ctypes.Structure):
            _fields_ = [
                ("left", ctypes.c_long), ("top", ctypes.c_long),
                ("right", ctypes.c_long), ("bottom", ctypes.c_long),
            ]

        class _MONITORINFO(ctypes.Structure):
            _fields_ = [
                ("cbSize", wintypes.DWORD),
                ("rcMonitor", _RECT),
                ("rcWork", _RECT),
                ("dwFlags", wintypes.DWORD),
            ]

        class _DISPLAY_DEVICEW(ctypes.Structure):
            _fields_ = [
                ("cb", wintypes.DWORD),
                ("DeviceName", wintypes.WCHAR * 32),
                ("DeviceString", wintypes.WCHAR * 128),
                ("StateFlags", wintypes.DWORD),
                ("DeviceID", wintypes.WCHAR * 128),
                ("DeviceKey", wintypes.WCHAR * 128),
            ]

        # DEVMODEW — union tail is complex; we only need the header fields up
        # to dmDisplayFrequency, so declare just those members. The display
        # union variant starts with POINTL dmPosition (8 bytes).
        class _POINTL(ctypes.Structure):
            _fields_ = [("x", wintypes.LONG), ("y", wintypes.LONG)]

        class _DEVMODEW(ctypes.Structure):
            _fields_ = [
                ("dmDeviceName", wintypes.WCHAR * 32),
                ("dmSpecVersion", wintypes.WORD),
                ("dmDriverVersion", wintypes.WORD),
                ("dmSize", wintypes.WORD),
                ("dmDriverExtra", wintypes.WORD),
                ("dmFields", wintypes.DWORD),
                ("dmPosition", _POINTL),
                ("dmDisplayOrientation", wintypes.DWORD),
                ("dmDisplayFixedOutput", wintypes.DWORD),
                ("dmColor", wintypes.SHORT),
                ("dmDuplex", wintypes.SHORT),
                ("dmYResolution", wintypes.SHORT),
                ("dmTTOption", wintypes.SHORT),
                ("dmCollate", wintypes.SHORT),
                ("dmFormName", wintypes.WCHAR * 32),
                ("dmLogPixels", wintypes.WORD),
                ("dmBitsPerPel", wintypes.DWORD),
                ("dmPelsWidth", wintypes.DWORD),
                ("dmPelsHeight", wintypes.DWORD),
                ("dmDisplayFlags", wintypes.DWORD),
                ("dmDisplayFrequency", wintypes.DWORD),
            ]

        @ctypes.WINFUNCTYPE(ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int)
        def _enum_callback(hmon, hdc, lprect, _lparam):
            if hmon:
                try:
                    name = f"Monitor {hmon}"
                    info = _MONITORINFO()
                    info.cbSize = ctypes.sizeof(_MONITORINFO)
                    if user32.GetMonitorInfoW(hmon, ctypes.byref(info)):
                        dev = _DISPLAY_DEVICEW()
                        dev.cb = ctypes.sizeof(_DISPLAY_DEVICEW)
                        if user32.EnumDisplayDevicesW(None, 0, ctypes.byref(dev), 0):
                            name = dev.DeviceName.strip("\0") or name
                        is_primary = bool(info.dwFlags & 1)  # MONITORINFOF_PRIMARY
                        displays.append({
                            "name": name,
                            "width": int(info.rcMonitor.right - info.rcMonitor.left),
                            "height": int(info.rcMonitor.bottom - info.rcMonitor.top),
                            "refresh_hz": 0,
                            "is_primary": is_primary,
                        })
                except Exception:
                    pass
            return 1

        user32.EnumDisplayMonitors(0, 0, _enum_callback, 0)

        # Fill refresh rate for each monitor via EnumDisplaySettingsW.
        user32.EnumDisplaySettingsW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, ctypes.c_void_p]
        user32.EnumDisplaySettingsW.restype = wintypes.BOOL
        for d in displays:
            devmode = _DEVMODEW()
            devmode.dmSize = ctypes.sizeof(_DEVMODEW)
            if user32.EnumDisplaySettingsW(d["name"], -1, ctypes.byref(devmode)):
                d["refresh_hz"] = int(getattr(devmode, "dmDisplayFrequency", 0) or 0)

        return {"displays": displays}
