"""
automation/system_ops.py

Windows system operations: brightness, WiFi, Bluetooth, airplane mode,
battery, CPU/RAM/disk/network stats, Task/Device Manager, Control Panel,
sign out, delayed shutdown/restart.
"""

from __future__ import annotations

import logging
import os
import re
import subprocess
import time
from typing import Any

logger = logging.getLogger(__name__)

# =========================================================================
# Brightness
# =========================================================================


def _run_powershell(script: str, timeout: int = 10) -> str:
    """Run a PowerShell command and return stdout."""
    try:
        result = subprocess.run(
            ["powershell", "-NoProfile", "-Command", script],
            capture_output=True, text=True, timeout=timeout,
        )
        return result.stdout.strip()
    except subprocess.TimeoutExpired:
        logger.warning("PowerShell command timed out after %ds", timeout)
        return ""
    except Exception as exc:
        logger.warning("PowerShell command failed: %s", exc)
        return ""


# ---------------------------------------------------------------------------
# Brightness
# ---------------------------------------------------------------------------

def get_brightness() -> dict:
    """Get current display brightness (0-100)."""
    script = """
try {
    $m = Get-WmiObject -Namespace root/wmi -Class WmiMonitorBrightness -ErrorAction Stop
    if ($m) { $m.CurrentBrightness } else { -1 }
} catch { -1 }
"""
    val = _run_powershell(script)
    if val and val != "-1":
        return {
            "success": True,
            "brightness": int(val),
            "message": f"Brightness is at {val}%.",
        }
    return {"success": False, "message": "Could not read brightness level."}


def set_brightness(level: int) -> dict:
    """Set display brightness to *level* (0-100)."""
    level = max(0, min(100, int(level)))
    script = f"""
try {{
    $m = Get-WmiObject -Namespace root/wmi -Class WmiMonitorBrightnessMethods -ErrorAction Stop
    if ($m) {{ $m.WmiSetBrightness({level}, 0) | Out-Null; $true }} else {{ $false }}
}} catch {{ $false }}
"""
    ok = _run_powershell(script)
    if ok == "True":
        logger.info("Brightness set to %d%%", level)
        return {"success": True, "message": f"Brightness set to {level}%.", "level": level}
    return {"success": False, "message": "Could not set brightness."}


# ---------------------------------------------------------------------------
# WiFi
# ---------------------------------------------------------------------------

_WIFI_NAME_PATTERN = re.compile(r"^\s*SSID\s+:\s+(.+)$", re.MULTILINE)


def get_wifi_status() -> dict:
    """Return current WiFi status."""
    out = _run_powershell("netsh wlan show interfaces")
    if not out:
        return {"success": False, "message": "Could not query WiFi status."}
    ssid_match = _WIFI_NAME_PATTERN.search(out)
    connected = ssid_match is not None
    ssid = ssid_match.group(1).strip() if connected else ""
    return {
        "success": True,
        "connected": connected,
        "ssid": ssid,
        "message": f"WiFi is {'connected to ' + ssid if connected else 'disconnected'}.",
    }


def wifi_on() -> dict:
    """Reconnect WiFi (netsh wlan connect)."""
    out = _run_powershell("netsh wlan connect")
    if "successfully" in out.casefold() or "there is no profile" not in out.casefold():
        logger.info("WiFi reconnected")
        return {"success": True, "message": "WiFi turned on."}
    return {"success": False, "message": "Could not turn on WiFi."}


def wifi_off() -> dict:
    """Disconnect WiFi."""
    out = _run_powershell("netsh wlan disconnect")
    if "successfully" in out.casefold() or "not connected" in out.casefold():
        logger.info("WiFi disconnected")
        return {"success": True, "message": "WiFi turned off."}
    return {"success": False, "message": "Could not turn off WiFi."}


# ---------------------------------------------------------------------------
# Bluetooth
# ---------------------------------------------------------------------------


def get_bluetooth_status() -> dict:
    """Check if the Bluetooth radio is enabled."""
    script = """
$radio = Get-PnpDevice -Class Bluetooth -ErrorAction SilentlyContinue `
    | Where-Object { $_.FriendlyName -like '*Radio*' } `
    | Select-Object -First 1
if ($radio) { $radio.Status } else { 'NotFound' }
"""
    status = _run_powershell(script)
    if status == "OK":
        return {"success": True, "enabled": True, "message": "Bluetooth is on."}
    if status == "Error":
        return {"success": True, "enabled": False, "message": "Bluetooth is off."}
    return {"success": False, "message": f"Bluetooth status unknown ({status})."}


def bluetooth_on() -> dict:
    """Enable the Bluetooth radio."""
    script = """
try {
    $radio = Get-PnpDevice -Class Bluetooth -ErrorAction Stop `
        | Where-Object { $_.FriendlyName -like '*Radio*' } `
        | Select-Object -First 1
    if (-not $radio) { 'NoDevice'; exit }
    Enable-PnpDevice -InstanceId $radio.InstanceId -Confirm:$false | Out-Null
    'OK'
} catch { 'Failed' }
"""
    ok = _run_powershell(script)
    if ok == "OK":
        return {"success": True, "message": "Bluetooth turned on."}
    return {"success": False, "message": "Could not turn on Bluetooth (may need admin rights)."}


def bluetooth_off() -> dict:
    """Disable the Bluetooth radio."""
    script = """
try {
    $radio = Get-PnpDevice -Class Bluetooth -ErrorAction Stop `
        | Where-Object { $_.FriendlyName -like '*Radio*' } `
        | Select-Object -First 1
    if (-not $radio) { 'NoDevice'; exit }
    Disable-PnpDevice -InstanceId $radio.InstanceId -Confirm:$false | Out-Null
    'OK'
} catch { 'Failed' }
"""
    ok = _run_powershell(script)
    if ok == "OK":
        return {"success": True, "message": "Bluetooth turned off."}
    return {"success": False, "message": "Could not turn off Bluetooth (may need admin rights)."}


# ---------------------------------------------------------------------------
# Airplane mode
# ---------------------------------------------------------------------------

def get_airplane_mode_status() -> dict:
    """Check if airplane mode is enabled."""
    script = """
try {
    Add-Type -AssemblyName System.Runtime.WindowsRuntime -ErrorAction Stop
    $asTaskGeneric = ([System.WindowsRuntimeSystemExtensions].GetMethods() `
        | Where-Object { $_.Name -eq 'AsTask' -and $_.GetParameters().Count -eq 1 `
            -and $_.GetParameters()[0].ParameterType.Name -eq 'IAsyncOperation`1' })[0]
    $radio = [Windows.Devices.Radios.Radio,Windows.Devices.Radios,ContentType=WindowsRuntime]::RequestAccessAsync()
    $task = $asTaskGeneric.MakeGenericMethod([Windows.Devices.Radios.RadioAccessStatus]).Invoke($null, @($radio))
    $task.Wait()
    $radios = [Windows.Devices.Radios.Radio,Windows.Devices.Radios,ContentType=WindowsRuntime]::GetRadiosAsync()
    $task2 = $asTaskGeneric.MakeGenericMethod(([Windows.Foundation.Collections.IVectorView[Windows.Devices.Radios.Radio]])).Invoke($null, @($radios))
    $task2.Wait()
    foreach ($r in $task2.Result) {
        if ($r.Kind -eq 'Other') {
            $r.State
        }
    }
} catch { 'Unknown' }
"""
    state = _run_powershell(script)
    if state == "On":
        return {"success": True, "enabled": True, "message": "Airplane mode is on."}
    if state == "Off":
        return {"success": True, "enabled": False, "message": "Airplane mode is off."}
    return {"success": False, "message": f"Could not read airplane mode ({state})."}


def airplane_mode_on() -> dict:
    """Turn on airplane mode via Windows Runtime API."""
    script = """
try {
    Add-Type -AssemblyName System.Runtime.WindowsRuntime -ErrorAction Stop
    $asTaskGeneric = ([System.WindowsRuntimeSystemExtensions].GetMethods() `
        | Where-Object { $_.Name -eq 'AsTask' -and $_.GetParameters().Count -eq 1 `
            -and $_.GetParameters()[0].ParameterType.Name -eq 'IAsyncOperation`1' })[0]
    $radios = [Windows.Devices.Radios.Radio,Windows.Devices.Radios,ContentType=WindowsRuntime]::GetRadiosAsync()
    $task = $asTaskGeneric.MakeGenericMethod(([Windows.Foundation.Collections.IVectorView[Windows.Devices.Radios.Radio]])).Invoke($null, @($radios))
    $task.Wait()
    foreach ($r in $task.Result) {
        $op = $r.SetStateAsync([Windows.Devices.Radios.RadioState]::On)
        $t = $asTaskGeneric.MakeGenericMethod([Windows.Devices.Radios.RadioAccessStatus]).Invoke($null, @($op))
        $t.Wait()
    }
    'OK'
} catch { 'Failed' }
"""
    ok = _run_powershell(script, timeout=15)
    if ok == "OK":
        return {"success": True, "message": "Airplane mode turned on."}
    return {"success": False, "message": "Could not turn on airplane mode."}


def airplane_mode_off() -> dict:
    """Turn off airplane mode via Windows Runtime API."""
    script = """
try {
    Add-Type -AssemblyName System.Runtime.WindowsRuntime -ErrorAction Stop
    $asTaskGeneric = ([System.WindowsRuntimeSystemExtensions].GetMethods() `
        | Where-Object { $_.Name -eq 'AsTask' -and $_.GetParameters().Count -eq 1 `
            -and $_.GetParameters()[0].ParameterType.Name -eq 'IAsyncOperation`1' })[0]
    $radios = [Windows.Devices.Radios.Radio,Windows.Devices.Radios,ContentType=WindowsRuntime]::GetRadiosAsync()
    $task = $asTaskGeneric.MakeGenericMethod(([Windows.Foundation.Collections.IVectorView[Windows.Devices.Radios.Radio]])).Invoke($null, @($radios))
    $task.Wait()
    foreach ($r in $task.Result) {
        $op = $r.SetStateAsync([Windows.Devices.Radios.RadioState]::Off)
        $t = $asTaskGeneric.MakeGenericMethod([Windows.Devices.Radios.RadioAccessStatus]).Invoke($null, @($op))
        $t.Wait()
    }
    'OK'
} catch { 'Failed' }
"""
    ok = _run_powershell(script, timeout=15)
    if ok == "OK":
        return {"success": True, "message": "Airplane mode turned off."}
    return {"success": False, "message": "Could not turn off airplane mode."}


# ---------------------------------------------------------------------------
# Battery
# ---------------------------------------------------------------------------

def get_battery_status() -> dict:
    """Get battery percentage, charging state, and estimated remaining time."""
    script = """
try {
    $b = Get-WmiObject Win32_Battery -ErrorAction Stop
    if (-not $b) { 'NoBattery'; exit }
    foreach ($bat in $b) {
        $pct = $bat.EstimatedChargeRemaining
        $status = switch ($bat.BatteryStatus) {
            1 { 'Discharging' }
            2 { 'PluggedIn' }
            3 { 'FullyCharged' }
            4 { 'Low' }
            5 { 'Critical' }
            6 { 'Charging' }
            7 { 'ChargingHigh' }
            8 { 'ChargingLow' }
            9 { 'ChargingCritical' }
            10 { 'Undefined' }
            11 { 'PartiallyCharged' }
            default { 'Unknown' }
        }
        $time = $bat.EstimatedRunTime
        "$pct|$status|$time"
    }
} catch { 'Error' }
"""
    out = _run_powershell(script)
    if out == "NoBattery":
        return {"success": True, "message": "No battery detected (desktop).", "has_battery": False}
    if out and out != "Error":
        parts = out.split("|")
        pct = int(parts[0]) if parts[0].isdigit() else 0
        status = parts[1] if len(parts) > 1 else "Unknown"
        run_time = int(parts[2]) if len(parts) > 2 and parts[2].isdigit() else 0
        time_str = f"{run_time} minutes remaining" if run_time else "calculating..."
        msg = f"Battery at {pct}%, {status}. {time_str}"
        return {"success": True, "message": msg, "percentage": pct, "status": status, "remaining_minutes": run_time}
    return {"success": False, "message": "Could not read battery status."}


# ---------------------------------------------------------------------------
# System stats (CPU / RAM / Disk / Network)
# ---------------------------------------------------------------------------

def get_cpu_usage() -> dict:
    """Get overall CPU usage percentage."""
    import psutil
    pct = psutil.cpu_percent(interval=0.5)
    cores = psutil.cpu_count()
    msg = f"CPU usage at {pct}% ({cores} cores)."
    return {"success": True, "message": msg, "cpu_percent": pct, "cores": cores}


def get_top_cpu_processes(limit: int = 5) -> dict:
    """Get the top CPU-consuming processes."""
    import psutil
    processes = []
    for proc in psutil.process_iter(["pid", "name", "cpu_percent"]):
        try:
            pinfo = proc.info
            if pinfo["cpu_percent"] is not None and pinfo["cpu_percent"] > 0:
                processes.append(pinfo)
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    processes.sort(key=lambda p: p["cpu_percent"], reverse=True)
    top = processes[:limit]
    lines = [f"{p['name']}: {p['cpu_percent']}%" for p in top]
    msg = "Top CPU processes:\\n" + "\\n".join(lines) if lines else "No processes using significant CPU."
    return {"success": True, "message": msg, "processes": top}


def get_ram_usage() -> dict:
    """Get RAM usage statistics."""
    import psutil
    mem = psutil.virtual_memory()
    total_gb = mem.total / (1024 ** 3)
    used_gb = mem.used / (1024 ** 3)
    pct = mem.percent
    msg = f"RAM at {pct}% ({used_gb:.1f} GB / {total_gb:.1f} GB)."
    return {"success": True, "message": msg, "ram_percent": pct, "used_gb": round(used_gb, 1), "total_gb": round(total_gb, 1)}


def get_disk_usage() -> dict:
    """Get disk usage for all mounted drives."""
    import psutil
    disks = []
    for part in psutil.disk_partitions():
        try:
            usage = psutil.disk_usage(part.mountpoint)
            disks.append({
                "mountpoint": part.mountpoint,
                "total_gb": round(usage.total / (1024 ** 3), 1),
                "used_gb": round(usage.used / (1024 ** 3), 1),
                "free_gb": round(usage.free / (1024 ** 3), 1),
                "percent": usage.percent,
            })
        except (PermissionError, OSError):
            continue
    lines = [f"{d['mountpoint']}: {d['percent']}% used ({d['used_gb']} GB / {d['total_gb']} GB)" for d in disks]
    msg = "Disk usage:\\n" + "\\n".join(lines) if lines else "No disk info available."
    return {"success": True, "message": msg, "disks": disks}


def get_network_usage() -> dict:
    """Get network I/O counters."""
    import psutil
    net = psutil.net_io_counters()
    sent_mb = net.bytes_sent / (1024 ** 2)
    recv_mb = net.bytes_recv / (1024 ** 2)
    msg = f"Network: {sent_mb:.1f} MB sent, {recv_mb:.1f} MB received."
    return {"success": True, "message": msg, "sent_mb": round(sent_mb, 1), "received_mb": round(recv_mb, 1)}


# ---------------------------------------------------------------------------
# System tools
# ---------------------------------------------------------------------------

_SYSTEM_TOOLS = {
    "task manager": ("taskmgr.exe", False),
    "device manager": ("devmgmt.msc", True),
    "control panel": ("control.exe", False),
}


def open_system_tool(name: str) -> dict:
    """Open a system tool by name (task manager, device manager, control panel)."""
    key = name.strip().casefold()
    entry = _SYSTEM_TOOLS.get(key)
    if not entry:
        return {"success": False, "message": f"Unknown tool: {name}"}
    exe, use_shell = entry
    try:
        if use_shell:
            subprocess.Popen([exe], shell=True)
        else:
            subprocess.Popen([exe], shell=False)
        return {"success": True, "message": f"Opened {name}.", "details": {"tool": name}}
    except Exception as exc:
        return {"success": False, "message": f"Could not open {name}: {exc}"}


# ---------------------------------------------------------------------------
# Sign out
# ---------------------------------------------------------------------------

def sign_out() -> dict:
    """Sign out the current user."""
    try:
        subprocess.run(["shutdown", "/l"], check=True)
        return {"success": True, "message": "Signing out."}
    except Exception as exc:
        return {"success": False, "message": f"Could not sign out: {exc}"}


# ---------------------------------------------------------------------------
# Delayed shutdown / restart / cancel
# ---------------------------------------------------------------------------

def delayed_shutdown(minutes: int = 0, seconds: int = 0) -> dict:
    """Shut down after *minutes* (or immediately if both are 0)."""
    total_seconds = int(minutes * 60 + seconds)
    if total_seconds < 0:
        total_seconds = 0
    try:
        subprocess.run(["shutdown", "/s", "/t", str(total_seconds)], check=True)
        if total_seconds > 0:
            return {"success": True, "message": f"Computer will shut down in {total_seconds // 60} minutes."}
        return {"success": True, "message": "Shutting down."}
    except Exception as exc:
        return {"success": False, "message": f"Could not schedule shutdown: {exc}"}


def delayed_restart(minutes: int = 0, seconds: int = 0) -> dict:
    """Restart after *minutes* (or immediately if both are 0)."""
    total_seconds = int(minutes * 60 + seconds)
    if total_seconds < 0:
        total_seconds = 0
    try:
        subprocess.run(["shutdown", "/r", "/t", str(total_seconds)], check=True)
        if total_seconds > 0:
            return {"success": True, "message": f"Computer will restart in {total_seconds // 60} minutes."}
        return {"success": True, "message": "Restarting."}
    except Exception as exc:
        return {"success": False, "message": f"Could not schedule restart: {exc}"}


def cancel_delayed_shutdown() -> dict:
    """Cancel a pending shutdown/restart."""
    try:
        subprocess.run(["shutdown", "/a"], check=True)
        return {"success": True, "message": "Cancelled scheduled shutdown/restart."}
    except Exception as exc:
        return {"success": False, "message": f"Could not cancel: {exc}"}


# ---------------------------------------------------------------------------
# Format drive
# ---------------------------------------------------------------------------


def format_drive(drive: str) -> dict:
    """Format a drive.

    Requires explicit confirmation via the Safety Framework before calling
    this function.  Drive letter should be a single letter (e.g. 'D').
    """
    drive = drive.strip().rstrip(":\\/").upper()
    if not drive or len(drive) > 2:
        return {"success": False, "message": f"Invalid drive letter: {drive!r}."}

    if drive in ("C",):
        return {"success": False, "message": "Cannot format the system drive (C:)."}

    # Verify the drive exists and is accessible
    drive_path = f"{drive}:\\"
    if not os.path.exists(drive_path):
        return {"success": False, "message": f"Drive {drive}: does not appear to be accessible."}

    logger.warning("FORMAT_DRIVE Action=format_drive Drive=%s", drive)

    try:
        subprocess.run(
            ["format", f"{drive}:", "/Q", "/Y"],
            capture_output=True, timeout=30,
        )
        return {"success": True, "message": f"Drive {drive}: formatted."}
    except subprocess.TimeoutExpired:
        return {"success": False, "message": f"Format of {drive}: timed out."}
    except Exception as exc:
        return {"success": False, "message": f"Could not format {drive}: {exc}"}
