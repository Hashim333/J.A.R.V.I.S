"""
automation/apps.py

Windows application management: launch, close, focus, verify, and system
commands (volume, screenshot, shutdown, settings, folders).

This module has no dependencies on Parser, Planner, or Executor. It is the
lowest automation layer.
"""

from __future__ import annotations

import ctypes
import json
import logging
import os
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable

import psutil


def _get_window_pid(hwnd: int) -> int:
    """Return the PID of the process that owns the given window handle."""
    user32 = ctypes.windll.user32
    pid = ctypes.c_ulong()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    return pid.value


class AppOperationError(Exception):
    """Raised when launching, closing, or querying an app fails."""


class AppNotFoundError(AppOperationError):
    """Raised when a supported application executable cannot be found."""


_WINDOWS_ONLY_MESSAGE = "Desktop app automation is only supported on Windows."


@dataclass(frozen=True)
class _ChromeProfile:
    directory: str
    display_name: str


@dataclass(frozen=True)
class _AppSpec:
    process_name: str
    candidates: tuple[str | Path, ...]


def _program_files() -> Path:
    return Path(os.environ.get("ProgramFiles", "C:/Program Files"))


def _program_files_x86() -> Path:
    return Path(os.environ.get("ProgramFiles(x86)", "C:/Program Files (x86)"))


def _windows_dir() -> Path:
    return Path(os.environ.get("WINDIR", "C:/Windows"))


def _current_user_home() -> Path:
    user_profile = os.environ.get("USERPROFILE")
    if user_profile:
        return Path(user_profile)

    home_drive = os.environ.get("HOMEDRIVE")
    home_path = os.environ.get("HOMEPATH")
    if home_drive and home_path:
        return Path(home_drive) / home_path.lstrip("\\/")

    username = os.environ.get("USERNAME")
    if username:
        return Path("C:/Users") / username

    raise AppOperationError(
        "Could not determine current Windows user from environment variables."
    )


# ---------------------------------------------------------------------------
# Application alias normalisation
# ---------------------------------------------------------------------------

_APP_ALIASES: dict[str, str] = {
    "chrome": "chrome",
    "google chrome": "chrome",
    "chrome browser": "chrome",
    "browser": "chrome",
    "my browser": "chrome",
    "calculator": "calculator",
    "calc": "calculator",
    "windows calculator": "calculator",
    "notepad": "notepad",
    "paint": "paint",
    "mspaint": "paint",
    "edge": "edge",
    "microsoft edge": "edge",
    "ms edge": "edge",
    "explorer": "explorer",
    "file explorer": "explorer",
    "vscode": "vscode",
    "vs code": "vscode",
    "code": "vscode",
    "visual studio code": "vscode",
    "code editor": "vscode",
    "cmd": "cmd",
    "command prompt": "cmd",
    "cmd prompt": "cmd",
    "powershell": "powershell",
    "terminal": "powershell",
}


def normalize_application_name(name: str) -> str:
    if not isinstance(name, str) or not name.strip():
        raise AppOperationError("Application name must be a non-empty string.")
    key = name.strip().casefold()
    return _APP_ALIASES.get(key, key)


# ---------------------------------------------------------------------------
# Ambiguous app phrases → clarification
# ---------------------------------------------------------------------------

AMBIGUOUS_APP_PHRASES: dict[str, dict] = {
    "code": {
        "primary": "vscode",
        "question": "Did you mean Visual Studio Code or another application?",
    },
    "terminal": {
        "primary": "powershell",
        "question": "Did you mean PowerShell or Command Prompt?",
    },
    "browser": {
        "primary": "chrome",
        "question": "Did you mean Google Chrome or Microsoft Edge?",
    },
    "my browser": {
        "primary": "chrome",
        "question": "Did you mean Google Chrome or Microsoft Edge?",
    },
}


def is_ambiguous_app(name: str) -> str | None:
    key = name.strip().casefold()
    entry = AMBIGUOUS_APP_PHRASES.get(key)
    if entry:
        return entry["question"]
    return None


# ---------------------------------------------------------------------------
# App specs (known install locations)
# ---------------------------------------------------------------------------


def _app_specs() -> dict[str, _AppSpec]:
    system32 = _windows_dir() / "System32"
    user_home = _current_user_home()

    return {
        "notepad": _AppSpec(
            process_name="notepad.exe",
            candidates=(
                system32 / "notepad.exe",
                _windows_dir() / "notepad.exe",
                "notepad.exe",
            ),
        ),
        "calculator": _AppSpec(
            process_name="CalculatorApp.exe",
            candidates=(
                system32 / "calc.exe",
                "calc.exe",
            ),
        ),
        "chrome": _AppSpec(
            process_name="chrome.exe",
            candidates=(
                _program_files() / "Google" / "Chrome" / "Application" / "chrome.exe",
                _program_files_x86()
                / "Google"
                / "Chrome"
                / "Application"
                / "chrome.exe",
                user_home
                / "AppData"
                / "Local"
                / "Google"
                / "Chrome"
                / "Application"
                / "chrome.exe",
                "chrome.exe",
            ),
        ),
        "edge": _AppSpec(
            process_name="msedge.exe",
            candidates=(
                _program_files_x86()
                / "Microsoft"
                / "Edge"
                / "Application"
                / "msedge.exe",
                _program_files()
                / "Microsoft"
                / "Edge"
                / "Application"
                / "msedge.exe",
                "msedge.exe",
            ),
        ),
        "vscode": _AppSpec(
            process_name="Code.exe",
            candidates=(
                user_home
                / "AppData"
                / "Local"
                / "Programs"
                / "Microsoft VS Code"
                / "Code.exe",
                "Code.exe",
            ),
        ),
        "explorer": _AppSpec(
            process_name="explorer.exe",
            candidates=(
                _windows_dir() / "explorer.exe",
                "explorer.exe",
            ),
        ),
        "paint": _AppSpec(
            process_name="mspaint.exe",
            candidates=(
                system32 / "mspaint.exe",
                "mspaint.exe",
            ),
        ),
        "cmd": _AppSpec(
            process_name="cmd.exe",
            candidates=(
                system32 / "cmd.exe",
                "cmd.exe",
            ),
        ),
        "powershell": _AppSpec(
            process_name="powershell.exe",
            candidates=(
                system32 / "WindowsPowerShell" / "v1.0" / "powershell.exe",
                "powershell.exe",
            ),
        ),
    }


def _app_spec(name: str) -> _AppSpec:
    key = normalize_application_name(name)
    specs = _app_specs()
    try:
        return specs[key]
    except KeyError:
        raise AppOperationError(
            f"Unsupported application {name!r}. Supported applications are: "
            f"{', '.join(sorted(specs))}."
        ) from None


# ---------------------------------------------------------------------------
# Executable discovery
# ---------------------------------------------------------------------------


def _resolve_launch_candidates(name: str) -> list[str]:
    spec = _app_spec(name)
    checked: list[str] = []
    resolved: list[str] = []

    for candidate in spec.candidates:
        if isinstance(candidate, Path):
            exists = candidate.exists()
            checked.append(f"{candidate} (exists={exists})")
            if exists:
                resolved.append(str(candidate))
            continue

        checked.append(candidate)
        path_match = shutil.which(candidate)
        if path_match:
            resolved.append(path_match)

    if resolved:
        return resolved

    error_msg = f"Could not find an executable for {name!r}. Checked: {', '.join(checked)}."
    raise AppNotFoundError(error_msg)


def find_application(name: str) -> str | None:
    """Return the full path to an application executable, or None."""
    try:
        candidates = _resolve_launch_candidates(name)
        return candidates[0] if candidates else None
    except (AppNotFoundError, AppOperationError):
        return None


# ---------------------------------------------------------------------------
# Process management
# ---------------------------------------------------------------------------


def _process_name_for(name: str) -> str:
    return _app_spec(name).process_name


def _matches_process(proc: psutil.Process, process_name: str) -> bool:
    try:
        return proc.name().casefold() == process_name.casefold()
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        return False


def _find_processes(name: str) -> list[psutil.Process]:
    """Return all running processes for a given app name."""
    process_name = _process_name_for(name)
    matches: list[psutil.Process] = []
    try:
        for proc in psutil.process_iter(["name", "pid"]):
            if _matches_process(proc, process_name):
                matches.append(proc)
    except Exception:
        pass
    return matches


def is_running(name: str) -> bool:
    """Return True when the supported application has a running process."""
    return len(_find_processes(name)) > 0


def is_process_running(process_name: str) -> bool:
    """Return True when any process with the given name is running.

    Works with any executable name (e.g. 'zoom.exe', 'Code.exe').
    """
    if not process_name.casefold().endswith(".exe"):
        process_name = f"{process_name}.exe"
    try:
        for proc in psutil.process_iter(["name"]):
            try:
                if proc.info.get("name", "").casefold() == process_name.casefold():
                    return True
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
    except Exception:
        pass
    return False


def launch_executable(
    executable_path: str,
    extra_args: list[str] | None = None,
    process_name: str | None = None,
) -> dict:
    """Launch an arbitrary executable by its full path.

    Returns a structured result dict with success, message, and details.
    Does NOT use the hardcoded app spec system.
    """
    if not os.path.isfile(executable_path):
        return {
            "success": False,
            "message": f"Executable not found: {executable_path}",
        }

    extra_args = extra_args or []
    command = [executable_path, *extra_args]

    try:
        subprocess.Popen(
            command,
            shell=False,
            creationflags=subprocess.CREATE_NEW_PROCESS_GROUP,
        )
    except OSError as exc:
        return {
            "success": False,
            "message": f"Could not launch {executable_path}: {exc}",
        }

    return {
        "success": True,
        "message": f"Launched {executable_path}.",
        "details": {
            "executable": executable_path,
            "process_name": process_name or os.path.basename(executable_path),
        },
    }


_PROTECTED_PROCESSES: frozenset = frozenset({
    "explorer.exe",
    "winlogon.exe",
    "csrss.exe",
    "services.exe",
    "dwm.exe",
    "System",
    "Idle",
    "System Idle Process",
    "svchost.exe",
    "smss.exe",
    "wininit.exe",
    "lsass.exe",
})


def collect_process_pids(process_name: str) -> set[int]:
    """Return the set of PIDs for all running processes matching *process_name*.
    Public wrapper — safe for external callers.
    """
    if not process_name.casefold().endswith(".exe"):
        process_name = f"{process_name}.exe"
    return _collect_target_pids(process_name)


def _collect_target_pids(process_name: str) -> set[int]:
    """Return the set of PIDs for all running processes matching *process_name*."""
    pids: set[int] = set()
    try:
        for proc in psutil.process_iter(["name", "pid"]):
            try:
                if proc.info.get("name", "").casefold() == process_name.casefold():
                    pids.add(proc.info["pid"])
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
    except Exception:
        pass
    return pids


def find_windows_for_process(process_name: str) -> list[dict]:
    """Return window info dicts for every top-level window owned by *process_name*.
    Each dict: {hwnd, title, pid}.  Public wrapper.
    """
    if not process_name.casefold().endswith(".exe"):
        process_name = f"{process_name}.exe"
    pids = _collect_target_pids(process_name)
    windows = _find_windows_for_pids(pids)
    return [{"hwnd": hwnd, "title": title, "pid": pid} for hwnd, title, pid in windows]


def _find_windows_for_pids(
    target_pids: set[int],
) -> list[tuple[int, str, int]]:
    """Return (hwnd, title, pid) for every top-level window whose PID is in *target_pids*."""
    results: list[tuple[int, str, int]] = []
    try:
        import pygetwindow as gw
        for window in gw.getAllWindows():
            try:
                hwnd = window._hWnd
                if not hwnd:
                    continue
                pid = _get_window_pid(hwnd)
                if pid in target_pids:
                    results.append((hwnd, window.title.strip(), pid))
            except Exception:
                pass
    except Exception:
        pass
    return results


def _find_uwp_windows_by_title(display_name: str) -> list[tuple[int, str, int]]:
    """Find windows owned by ANY process whose title contains *display_name*.

    Some applications (UWP/MSIX packaged, e.g. Calculator) have their window
    owned by a host process (ApplicationFrameHost) rather than the application
    process itself.  This fallback matches window titles as a last resort.
    """
    results: list[tuple[int, str, int]] = []
    if not display_name:
        return results
    try:
        import pygetwindow as gw
        pattern = display_name.casefold().strip()
        for window in gw.getAllWindows():
            try:
                title = window.title.strip()
                if not title:
                    continue
                if pattern in title.casefold():
                    hwnd = window._hWnd
                    if hwnd:
                        pid = _get_window_pid(hwnd)
                        results.append((hwnd, title, pid))
            except Exception:
                pass
    except Exception:
        pass
    return results


def close_process(
    process_name: str,
    wait_seconds: float = 3.0,
    display_name: str | None = None,
) -> dict:
    """Gracefully close a process by finding its windows and sending WM_CLOSE.

    Only windows belonging to the specified process are closed.
    For UWP/MSIX apps whose windows are hosted by a separate process
    (e.g. ApplicationFrameHost), a title-based fallback is attempted
    when *display_name* is provided.

    Does NOT force-kill.  Returns ``needs_force_close`` if still running.
    """
    if not process_name.casefold().endswith(".exe"):
        process_name = f"{process_name}.exe"

    logger = logging.getLogger(__name__)
    logger.info("Intent=CLOSE_APPLICATION Action=close_process Target=%s", process_name)

    target_pids = _collect_target_pids(process_name)
    if not target_pids:
        logger.info("Intent=CLOSE_APPLICATION Action=close_process Target=%s Result=not_running", process_name)
        return {
            "success": True,
            "message": f"{process_name} is not running.",
            "details": {"process": process_name, "method": "none_needed"},
        }

    # Graceful close: send WM_CLOSE only to windows that belong to target PIDs
    window_count = 0
    try:
        import pygetwindow as gw
        for window in gw.getAllWindows():
            try:
                hwnd = window._hWnd
                if not hwnd:
                    continue
                pid = _get_window_pid(hwnd)
                if pid in target_pids:
                    title = window.title.strip()
                    logger.info(
                        "Intent=CLOSE_APPLICATION Action=send_wm_close PID=%d HWND=%d Title=%s",
                        pid, hwnd, title or "(untitled)",
                    )
                    window.close()
                    window_count += 1
            except Exception:
                pass
    except Exception:
        pass

    # Title-based fallback for UWP apps whose windows are hosted by
    # a framework process (e.g. ApplicationFrameHost).
    if window_count == 0 and display_name:
        fallback_windows = _find_uwp_windows_by_title(display_name)
        if fallback_windows:
            logger.info(
                "Intent=CLOSE_APPLICATION Action=uwp_fallback Target=%s Windows=%d",
                process_name, len(fallback_windows),
            )
            try:
                import pygetwindow as gw
                for window in gw.getAllWindows():
                    try:
                        hwnd = window._hWnd
                        if not hwnd:
                            continue
                        title = window.title.strip()
                        if not title:
                            continue
                        if display_name.casefold() in title.casefold():
                            pid = _get_window_pid(hwnd)
                            logger.info(
                                "Intent=CLOSE_APPLICATION Action=send_wm_close_uwp PID=%d HWND=%d Title=%s",
                                pid, hwnd, title,
                            )
                            window.close()
                            window_count += 1
                    except Exception:
                        pass
            except Exception:
                pass

    was_sent = False
    if window_count > 0:
        was_sent = True

    # Graceful terminate via psutil — only target processes
    try:
        for proc in psutil.process_iter(["name", "pid"]):
            try:
                if proc.info.get("name", "").casefold() == process_name.casefold():
                    logger.info(
                        "Intent=CLOSE_APPLICATION Action=terminate PID=%d",
                        proc.info["pid"],
                    )
                    proc.terminate()
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
    except Exception:
        pass

    # Verify closed with wait
    deadline = time.monotonic() + wait_seconds
    while time.monotonic() < deadline:
        if not is_process_running(process_name):
            logger.info(
                "Intent=CLOSE_APPLICATION Action=close_process Target=%s Result=success",
                process_name,
            )
            return {
                "success": True,
                "message": f"Closed {process_name}.",
                "details": {"process": process_name, "method": "graceful" if was_sent else "terminate"},
            }
        time.sleep(0.2)

    logger.info(
        "Intent=CLOSE_APPLICATION Action=close_process Target=%s Result=still_running",
        process_name,
    )
    return {
        "success": False,
        "message": f"Failed to close {process_name}. Process is still running.",
        "details": {"process": process_name},
        "needs_force_close": True,
    }


def force_process_kill(process_name: str) -> dict:
    """Force-kill a process via taskkill /F /IM (targets only the given image name).

    Returns a structured result dict.
    """
    if not process_name.casefold().endswith(".exe"):
        process_name = f"{process_name}.exe"

    logger = logging.getLogger(__name__)
    logger.info("Intent=CLOSE_APPLICATION Action=force_kill Target=%s", process_name)

    target_pids = _collect_target_pids(process_name)
    logger.info(
        "Intent=CLOSE_APPLICATION Action=force_kill Target=%s PIDs=%s",
        process_name,
        sorted(target_pids),
    )

    try:
        subprocess.run(
            ["taskkill", "/F", "/IM", process_name],
            capture_output=True,
            timeout=5,
        )
    except Exception:
        pass

    deadline = time.monotonic() + 3.0
    while time.monotonic() < deadline:
        if not is_process_running(process_name):
            logger.info(
                "Intent=CLOSE_APPLICATION Action=force_kill Target=%s Result=success",
                process_name,
            )
            return {
                "success": True,
                "message": f"Force closed {process_name}.",
                "details": {"process": process_name, "method": "force", "pids": sorted(target_pids)},
            }
        time.sleep(0.2)

    logger.warning(
        "Intent=CLOSE_APPLICATION Action=force_kill Target=%s Result=failed",
        process_name,
    )
    return {
        "success": False,
        "message": f"Failed to force close {process_name}. Process is still running.",
        "details": {"process": process_name},
    }


def _window_op(
    op_name: str,
    process_name: str,
    window_method: str,
    display_name: str | None = None,
) -> dict:
    """Generic window operation (focus/minimize/maximize/restore).

    Uses PID-based matching so only windows belonging to the target process
    are affected. Falls back to title-based matching for UWP apps when
    *display_name* is provided.
    """
    logger = logging.getLogger(__name__)
    action = op_name.upper()

    if not process_name.casefold().endswith(".exe"):
        process_name = f"{process_name}.exe"
    if not is_process_running(process_name):
        logger.info("Intent=%s_APPLICATION Target=%s Result=not_running", action, process_name)
        return {"success": False, "message": f"{process_name} is not running."}

    target_pids = _collect_target_pids(process_name)
    if not target_pids:
        logger.info("Intent=%s_APPLICATION Target=%s PIDs=empty Result=not_running", action, process_name)
        return {"success": False, "message": f"{process_name} is not running."}

    logger.info(
        "Intent=%s_APPLICATION Target=%s PIDs=%s",
        action, process_name, sorted(target_pids),
    )

    affected = 0
    total_found = 0
    exc = None

    try:
        import pygetwindow as gw

        for window in gw.getAllWindows():
            try:
                hwnd = window._hWnd
                if not hwnd:
                    continue
                pid = _get_window_pid(hwnd)
                if pid not in target_pids:
                    continue
                total_found += 1
                title = window.title.strip()
                logger.info(
                    "Intent=%s_APPLICATION Target=%s PID=%d HWND=%d Title=%s",
                    action, process_name, pid, hwnd, title or "(untitled)",
                )
                getattr(window, window_method)()
                affected += 1
            except Exception as e:
                exc = e
                continue
    except Exception as e:
        exc = e

    # UWP fallback: windows hosted by ApplicationFrameHost
    if affected == 0 and display_name and not exc:
        try:
            import pygetwindow as gw
            pattern = display_name.casefold().strip()
            for window in gw.getAllWindows():
                try:
                    title = window.title.strip()
                    if not title:
                        continue
                    if pattern in title.casefold():
                        hwnd = window._hWnd
                        if not hwnd:
                            continue
                        pid = _get_window_pid(hwnd)
                        total_found += 1
                        logger.info(
                            "Intent=%s_APPLICATION Target=%s Action=uwp_fallback PID=%d HWND=%d Title=%s",
                            action, process_name, pid, hwnd, title,
                        )
                        getattr(window, window_method)()
                        affected += 1
                except Exception:
                    continue
        except Exception:
            pass

    if affected > 0:
        logger.info(
            "Intent=%s_APPLICATION Target=%s Result=success Windows=%d",
            action, process_name, affected,
        )
        return {
            "success": True,
            "message": f"{op_name.title()} {process_name}.",
            "details": {"process": process_name, "op": op_name, "windows_affected": affected, "windows_found": total_found},
        }

    logger.warning(
        "Intent=%s_APPLICATION Target=%s Result=failed Windows=%d",
        action, process_name, total_found,
    )
    return {
        "success": False,
        "message": f"Could not {op_name} {process_name}.",
        "details": {"process": process_name, "op": op_name, "windows_found": total_found},
    }


def focus_process(
    process_name: str,
    display_name: str | None = None,
) -> dict:
    """Bring a window belonging to a process to the foreground.

    Uses PID-based matching so only the target process windows are focused.
    Falls back to title-based matching for UWP apps when *display_name* is
    provided (e.g. Calculator windows hosted by ApplicationFrameHost).
    """
    return _window_op("focus", process_name, "activate", display_name)


def minimize_process(
    process_name: str,
    display_name: str | None = None,
) -> dict:
    """Minimize all windows belonging to a process.

    Uses PID-based matching. UWP fallback via *display_name*.
    """
    return _window_op("minimize", process_name, "minimize", display_name)


def maximize_process(
    process_name: str,
    display_name: str | None = None,
) -> dict:
    """Maximize all windows belonging to a process.

    Uses PID-based matching. UWP fallback via *display_name*.
    """
    return _window_op("maximize", process_name, "maximize", display_name)


def restore_process(
    process_name: str,
    display_name: str | None = None,
) -> dict:
    """Restore (un-minimize) all windows belonging to a process.

    Uses PID-based matching. UWP fallback via *display_name*.
    """
    return _window_op("restore", process_name, "restore", display_name)


def verify_launch_by_process(process_name: str, timeout: float = 5.0) -> bool:
    """Poll until a process with the given name appears, or timeout."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if is_process_running(process_name):
            return True
        time.sleep(0.2)
    return is_process_running(process_name)


# ---------------------------------------------------------------------------
# Window control helpers
# ---------------------------------------------------------------------------



def close_all_user_apps() -> dict:
    """Close all user-facing applications except protected system processes.

    Returns a dict with success, message, and details about what was closed.
    """
    logger = logging.getLogger(__name__)
    closed: list[str] = []
    skipped: list[str] = []
    errors: list[str] = []

    for proc in psutil.process_iter(["name", "pid"]):
        try:
            name = proc.info.get("name", "")
            if not name:
                continue
            name_lower = name.casefold()
            # Skip protected system processes
            if name_lower in _PROTECTED_PROCESSES:
                skipped.append(name)
                continue
            # Skip processes without a window (background services)
            try:
                if not proc.is_running():
                    continue
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue

            # Try graceful close first
            try:
                import pygetwindow as gw
                for window in gw.getAllWindows():
                    try:
                        win_name = window.title.strip()
                        if win_name and name_lower.replace(".exe", "") in win_name.casefold():
                            window.close()
                    except Exception:
                        pass
            except Exception:
                pass

            # Terminate via psutil
            try:
                proc.terminate()
                closed.append(name)
            except (psutil.NoSuchProcess, psutil.AccessDenied) as exc:
                errors.append(f"{name}: {exc}")
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue

    if closed:
        logger.info("Closed user apps: %s", closed)
    if skipped:
        logger.info("Skipped protected processes: %s", skipped)
    if errors:
        logger.warning("Errors closing apps: %s", errors)

    if closed:
        return {
            "success": True,
            "message": f"Closed {len(closed)} application(s): {', '.join(closed[:5])}{'...' if len(closed) > 5 else ''}.",
            "details": {"closed": closed, "skipped": skipped, "errors": errors},
        }
    return {
        "success": True,
        "message": "No user applications to close.",
        "details": {"closed": [], "skipped": skipped},
    }


def verify_launch(name: str, timeout: float = 5.0) -> bool:
    """Poll until the app's process appears, or timeout."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if is_running(name):
            return True
        time.sleep(0.2)
    return is_running(name)


def verify_close(name: str, timeout: float = 5.0) -> bool:
    """Poll until the app's process disappears, or timeout."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if not is_running(name):
            return True
        time.sleep(0.2)
    return not is_running(name)


# ---------------------------------------------------------------------------
# Window focus
# ---------------------------------------------------------------------------


def focus_application(name: str) -> dict:
    """Bring an application window to the foreground."""
    import pygetwindow as gw

    normalized = normalize_application_name(name)
    process_name = _process_name_for(normalized)

    if not is_running(normalized):
        return {
            "success": False,
            "message": f"{name} is not running.",
        }

    try:
        windows = gw.getAllWindows()
    except Exception as exc:
        return {
            "success": False,
            "message": f"Could not enumerate windows: {exc}",
        }

    for window in windows:
        title = window.title.strip()
        if not title:
            continue
        title_lower = title.casefold()
        name_lower = normalized.casefold()
        if name_lower in title_lower:
            try:
                if window.isMinimized:
                    window.restore()
                window.activate()
                return {
                    "success": True,
                    "message": f"Brought {name} to the foreground.",
                }
            except Exception as exc:
                return {
                    "success": False,
                    "message": f"Could not focus {name}: {exc}",
                }

    process_name_lower = process_name.casefold().replace(".exe", "")
    for window in windows:
        title = window.title.strip().casefold()
        if process_name_lower in title:
            try:
                if window.isMinimized:
                    window.restore()
                window.activate()
                return {
                    "success": True,
                    "message": f"Brought {name} to the foreground.",
                }
            except Exception:
                pass

    return {
        "success": False,
        "message": f"{name} is running but no window was found to focus.",
    }


# ---------------------------------------------------------------------------
# Application launch
# ---------------------------------------------------------------------------


def _chrome_user_data_dir() -> Path:
    candidates: list[Path] = []
    local_app_data = os.environ.get("LOCALAPPDATA")
    if local_app_data:
        candidates.append(Path(local_app_data) / "Google" / "Chrome" / "User Data")
    candidates.append(
        _current_user_home()
        / "AppData"
        / "Local"
        / "Google"
        / "Chrome"
        / "User Data"
    )
    for candidate in candidates:
        if candidate.exists():
            return candidate
    raise AppOperationError(
        "Could not locate Chrome User Data directory. Checked: "
        f"{', '.join(str(c) for c in candidates)}."
    )


def _chrome_profiles() -> list[_ChromeProfile]:
    user_data_dir = _chrome_user_data_dir()
    local_state_path = user_data_dir / "Local State"
    if not local_state_path.exists():
        raise AppOperationError(f"Could not find Chrome Local State at {local_state_path}.")

    try:
        with local_state_path.open("r", encoding="utf-8") as file:
            local_state = json.load(file)
    except (json.JSONDecodeError, OSError) as exc:
        raise AppOperationError(f"Could not read Chrome Local State: {exc}") from exc

    info_cache = local_state.get("profile", {}).get("info_cache", {})
    if not isinstance(info_cache, dict) or not info_cache:
        raise AppOperationError("No Chrome profiles were found in Local State.")

    profiles: list[_ChromeProfile] = []
    for directory, profile_data in info_cache.items():
        if not isinstance(directory, str):
            continue
        if not isinstance(profile_data, dict):
            profile_data = {}
        display_name = (
            profile_data.get("name")
            or profile_data.get("shortcut_name")
            or profile_data.get("gaia_name")
            or directory
        )
        profiles.append(_ChromeProfile(directory=directory, display_name=str(display_name)))

    if not profiles:
        raise AppOperationError("No usable Chrome profiles were found in Local State.")
    return profiles


_MAX_VOICE_ATTEMPTS = 5


def _build_chrome_aliases(profiles: list[_ChromeProfile]) -> dict[str, int]:
    aliases: dict[str, int] = {}
    if profiles:
        for phrase in ("my profile", "mine", "default"):
            aliases[phrase] = 0
    return aliases


def _select_chrome_profile(
    profiles: list[_ChromeProfile],
    voice_input: Callable[[], str | None] | None = None,
) -> _ChromeProfile:
    from brain.profile_selection_parser import ProfileSelectionParser

    if len(profiles) == 1:
        return profiles[0]

    seen: set[str] = set()
    unique: list[_ChromeProfile] = []
    for p in profiles:
        key = p.display_name.casefold()
        if key not in seen:
            seen.add(key)
            unique.append(p)

    if len(unique) == 1:
        return unique[0]

    names = [p.display_name for p in unique]
    parser = ProfileSelectionParser(candidates=names, aliases=_build_chrome_aliases(unique))
    names_str = ", ".join(names)
    print("Which Chrome profile would you like to open?")
    for i, p in enumerate(unique, start=1):
        print(f"{i}. {p.display_name}")

    def _prompt() -> None:
        print(f"You can say the profile name ({names_str}) or the profile number.")

    attempts = 0
    while True:
        if voice_input is not None:
            raw = voice_input()
            if raw is None:
                attempts += 1
                if attempts >= _MAX_VOICE_ATTEMPTS:
                    raise AppOperationError("Could not recognise speech after multiple attempts.")
                print("I didn't catch that.")
                _prompt()
                continue
            utterance = raw.strip()
        else:
            sys.stdout.write("Chrome profile: ")
            sys.stdout.flush()
            utterance = (sys.__stdin__.readline() or "").strip()

        if utterance.casefold() == "cancel":
            raise AppOperationError("Chrome profile selection cancelled.")

        result = parser.parse(utterance)
        if result.low_confidence:
            print("I didn't catch that.")
            _prompt()
            if voice_input is not None:
                attempts += 1
                if attempts >= _MAX_VOICE_ATTEMPTS:
                    raise AppOperationError("Could not understand your choice after multiple attempts.")
                continue
            continue
        return unique[result.index]


def _popen(command: list[str]) -> None:
    try:
        subprocess.Popen(
            command,
            shell=False,
            creationflags=subprocess.CREATE_NEW_PROCESS_GROUP,
        )
    except FileNotFoundError:
        raise
    except OSError:
        raise


def _launch(name: str, extra_args: list[str] | None = None) -> bool:
    extra_args = extra_args or []
    try:
        candidates = _resolve_launch_candidates(name)
    except (AppNotFoundError, AppOperationError):
        raise

    for executable in candidates:
        command = [executable, *extra_args]
        try:
            _popen(command)
            time.sleep(0.5)
            return True
        except (FileNotFoundError, OSError):
            continue

    raise AppOperationError(f"Could not launch {name!r}.")


def _open_chrome(
    voice_input: Callable[[], str | None] | None = None,
    profile: str | None = None,
) -> bool:
    if profile:
        profile_str = profile.strip()
        if profile_str:
            known_profiles = _chrome_profiles()
            profile_lower = profile_str.casefold()
            for p in known_profiles:
                if p.display_name.casefold() == profile_lower or p.directory.casefold() == profile_lower:
                    return _launch("chrome", [f"--profile-directory={p.directory}"])
            # Profile not found — do not silently fall back to default
            raise AppOperationError(
                f"Chrome profile '{profile_str}' not found. Available: "
                f"{', '.join(p.display_name for p in known_profiles)}."
            )

    if voice_input is None:
        return _launch("chrome")

    known_profiles = _chrome_profiles()
    selected = _select_chrome_profile(known_profiles, voice_input)

    return _launch("chrome", [f"--profile-directory={selected.directory}"])


def open_app(
    name: str,
    voice_input: Callable[[], str | None] | None = None,
    profile: str | None = None,
    focus_if_running: bool = True,
) -> dict:
    """Launch a supported Windows desktop application with verification.

    Returns a structured result dict with success, message, and details.
    """
    if sys.platform != "win32":
        raise AppOperationError(_WINDOWS_ONLY_MESSAGE)

    if is_ambiguous_app(name):
        question = is_ambiguous_app(name)
        return {
            "success": False,
            "needs_clarification": True,
            "clarification_question": question,
            "message": question,
        }

    normalized = normalize_application_name(name)

    if focus_if_running and is_running(normalized):
        focus_result = focus_application(normalized)
        if focus_result["success"]:
            return {
                "success": True,
                "message": f"{name} is already running. Brought it to the foreground.",
                "details": {"action": "focused", "app": normalized},
            }
        return {
            "success": True,
            "message": f"{name} is already running.",
            "details": {"action": "already_running", "app": normalized},
        }

    try:
        if normalized == "chrome":
            _open_chrome(voice_input, profile)
        else:
            _launch(normalized)
    except (AppNotFoundError, AppOperationError) as exc:
        return {
            "success": False,
            "message": str(exc),
            "error": str(exc),
        }

    launched = verify_launch(normalized)
    if launched:
        return {
            "success": True,
            "message": f"{name} opened successfully.",
            "details": {"action": "launched", "app": normalized},
        }

    return {
        "success": False,
        "message": f"{name} could not be verified as running after launch.",
        "details": {"app": normalized},
    }


# ---------------------------------------------------------------------------
# Application close
# ---------------------------------------------------------------------------


def _close_gracefully(name: str) -> bool:
    """Send a graceful close signal to the first matching window."""
    import pygetwindow as gw
    normalized = normalize_application_name(name)

    try:
        windows = gw.getAllWindows()
    except Exception:
        return False

    name_lower = normalized.casefold()
    for window in windows:
        title = window.title.strip().casefold()
        if not title:
            continue
        if name_lower in title:
            try:
                window.close()
                return True
            except Exception:
                pass

    try:
        for proc in _find_processes(normalized):
            try:
                proc.terminate()
                return True
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
    except Exception:
        pass

    return False


def _close_force(name: str) -> bool:
    """Force-kill all processes matching the app."""
    normalized = normalize_application_name(name)
    process_name = _process_name_for(normalized)

    try:
        subprocess.run(
            ["taskkill", "/F", "/IM", process_name],
            capture_output=True,
            timeout=5,
        )
        return True
    except Exception:
        try:
            for proc in _find_processes(normalized):
                try:
                    proc.kill()
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    continue
            return True
        except Exception:
            return False


def close_app(name: str) -> dict:
    """Close an application gracefully, force if needed, and verify.

    Returns a structured result dict.
    """
    if sys.platform != "win32":
        raise AppOperationError(_WINDOWS_ONLY_MESSAGE)

    normalized = normalize_application_name(name)

    if not is_running(normalized):
        return {
            "success": True,
            "message": f"{name} is not running.",
            "details": {"app": normalized, "action": "none_needed"},
        }

    graceful = _close_gracefully(normalized)
    if graceful:
        closed = verify_close(normalized, timeout=3.0)
        if closed:
            return {
                "success": True,
                "message": f"{name} closed successfully.",
                "details": {"app": normalized, "method": "graceful"},
            }

    forced = _close_force(normalized)
    if forced:
        closed = verify_close(normalized, timeout=3.0)
        if closed:
            return {
                "success": True,
                "message": f"{name} closed successfully (forced).",
                "details": {"app": normalized, "method": "force"},
            }

    still_running = is_running(normalized)
    if still_running:
        return {
            "success": False,
            "message": f"Failed to close {name}. The process is still running after graceful close and force terminate.",
            "details": {"app": normalized},
        }

    return {
        "success": True,
        "message": f"{name} closed successfully.",
        "details": {"app": normalized, "method": "unknown"},
    }


# ---------------------------------------------------------------------------
# Special folders (Downloads, Documents, etc.)
# ---------------------------------------------------------------------------

_SPECIAL_FOLDERS: dict[str, str] = {
    "downloads": "shell:Downloads",
    "documents": "shell:Personal",
    "pictures": "shell:My Pictures",
    "music": "shell:My Music",
    "videos": "shell:My Video",
    "desktop": "shell:Desktop",
    "recent": "shell:Recent",
}


def open_special_folder(folder_name: str) -> dict:
    """Open a Windows special folder in Explorer."""
    key = folder_name.strip().casefold()
    shell_cmd = _SPECIAL_FOLDERS.get(key)
    if not shell_cmd:
        return {
            "success": False,
            "message": f"Unknown folder {folder_name!r}. Supported: {', '.join(_SPECIAL_FOLDERS)}.",
        }

    try:
        subprocess.Popen(["explorer", shell_cmd], shell=False)
        return {
            "success": True,
            "message": f"Opened {folder_name}.",
            "details": {"folder": key},
        }
    except Exception as exc:
        return {
            "success": False,
            "message": f"Could not open {folder_name}: {exc}",
        }


# ---------------------------------------------------------------------------
# Settings pages
# ---------------------------------------------------------------------------

_MS_SETTINGS_ALIASES: dict[str, str] = {
    "bluetooth": "ms-settings:bluetooth",
    "bluetooth & devices": "ms-settings:bluetooth",
    "wifi": "ms-settings:network-wifi",
    "network": "ms-settings:network",
    "display": "ms-settings:display",
    "sound": "ms-settings:sound",
    "personalization": "ms-settings:personalization",
    "system": "ms-settings:system",
    "apps": "ms-settings:appsfeatures",
    "default apps": "ms-settings:defaultapps",
    "about": "ms-settings:about",
    "update": "ms-settings:windowsupdate",
    "windows update": "ms-settings:windowsupdate",
    "power": "ms-settings:powersleep",
    "power & sleep": "ms-settings:powersleep",
    "storage": "ms-settings:storagesense",
    "multitasking": "ms-settings:multitasking",
    "gaming": "ms-settings:gaming-gamedvr",
    "printers": "ms-settings:printers",
    "devices": "ms-settings:devices",
    "mouse": "ms-settings:mousetouchpad",
    "keyboard": "ms-settings:keyboard",
    "typing": "ms-settings:typing",
    "language": "ms-settings:language",
    "date": "ms-settings:dateandtime",
    "time": "ms-settings:dateandtime",
    "region": "ms-settings:regionformatting",
    "sign-in": "ms-settings:signinoptions",
    "sign in": "ms-settings:signinoptions",
    "accounts": "ms-settings:accounts",
    "accessibility": "ms-settings:easeofaccess",
    "privacy": "ms-settings:privacy",
}


def open_settings(page: str = "") -> dict:
    """Open Windows Settings, optionally to a specific page."""
    uri = "ms-settings:"
    if page:
        key = page.strip().casefold()
        mapped = _MS_SETTINGS_ALIASES.get(key)
        if mapped:
            uri = mapped
        else:
            uri = f"ms-settings:{key.replace(' ', '')}"
    else:
        uri = "ms-settings:"

    try:
        subprocess.Popen(["start", uri], shell=True)
        topic = page or "main"
        return {
            "success": True,
            "message": f"Opened {topic} settings.",
            "details": {"settings_uri": uri},
        }
    except Exception as exc:
        return {
            "success": False,
            "message": f"Could not open settings: {exc}",
        }


# ---------------------------------------------------------------------------
# Volume control
# ---------------------------------------------------------------------------


def _get_volume_interface():
    """Return the Windows Core Audio AudioEndpointVolume interface via comtypes."""
    try:
        from comtypes import CLSCTX_ALL, CoInitialize, CoUninitialize
        from ctypes import POINTER, cast
        from pycaw.pycaw import AudioUtilities, IAudioEndpointVolume
    except ImportError:
        try:
            import comtypes
            CoInitialize = comtypes.CoInitialize
            CoUninitialize = comtypes.CoUninitialize
            CLSCTX_ALL = comtypes.CLSCTX_ALL
            from ctypes import POINTER, cast
            from comtypes import CLSCTX_ALL

            from pycaw.pycaw import AudioUtilities, IAudioEndpointVolume
        except ImportError:
            return None

    try:
        CoInitialize()
        devices = AudioUtilities.GetSpeakers()
        interface = devices.Activate(IAudioEndpointVolume._iid_, CLSCTX_ALL, None)
        volume = cast(interface, POINTER(IAudioEndpointVolume))
        return volume
    except Exception:
        try:
            CoUninitialize()
        except Exception:
            pass
        return None


def set_volume(level: int) -> dict:
    """Set system volume to a percentage (0–100)."""
    vol = _get_volume_interface()
    if vol is None:
        return {
            "success": False,
            "message": "Volume control is not available (pycaw not installed).",
        }

    try:
        scalar = max(0.0, min(1.0, level / 100.0))
        vol.SetMasterVolumeLevelScalar(scalar, None)
        return {
            "success": True,
            "message": f"Volume set to {level}%.",
            "details": {"level": level},
        }
    except Exception as exc:
        return {
            "success": False,
            "message": f"Could not set volume: {exc}",
        }


def mute_volume() -> dict:
    """Mute the system volume."""
    vol = _get_volume_interface()
    if vol is None:
        return {
            "success": False,
            "message": "Volume control is not available (pycaw not installed).",
        }

    try:
        vol.SetMute(1, None)
        return {
            "success": True,
            "message": "Volume muted.",
            "details": {"muted": True},
        }
    except Exception as exc:
        return {
            "success": False,
            "message": f"Could not mute volume: {exc}",
        }


def unmute_volume() -> dict:
    """Unmute the system volume."""
    vol = _get_volume_interface()
    if vol is None:
        return {
            "success": False,
            "message": "Volume control is not available.",
        }

    try:
        vol.SetMute(0, None)
        return {
            "success": True,
            "message": "Volume unmuted.",
            "details": {"muted": False},
        }
    except Exception as exc:
        return {
            "success": False,
            "message": f"Could not unmute volume: {exc}",
        }


def increase_volume(amount: int = 10) -> dict:
    """Increase volume by a percentage."""
    vol = _get_volume_interface()
    if vol is None:
        return {"success": False, "message": "Volume control is not available."}

    try:
        current = vol.GetMasterVolumeLevelScalar()
        new_level = min(1.0, current + (amount / 100.0))
        vol.SetMasterVolumeLevelScalar(new_level, None)
        pct = int(round(new_level * 100))
        return {
            "success": True,
            "message": f"Volume increased to {pct}%.",
            "details": {"level": pct},
        }
    except Exception as exc:
        return {
            "success": False,
            "message": f"Could not increase volume: {exc}",
        }


def decrease_volume(amount: int = 10) -> dict:
    """Decrease volume by a percentage."""
    vol = _get_volume_interface()
    if vol is None:
        return {"success": False, "message": "Volume control is not available."}

    try:
        current = vol.GetMasterVolumeLevelScalar()
        new_level = max(0.0, current - (amount / 100.0))
        vol.SetMasterVolumeLevelScalar(new_level, None)
        pct = int(round(new_level * 100))
        return {
            "success": True,
            "message": f"Volume decreased to {pct}%.",
            "details": {"level": pct},
        }
    except Exception as exc:
        return {
            "success": False,
            "message": f"Could not decrease volume: {exc}",
        }


# ---------------------------------------------------------------------------
# Screenshot
# ---------------------------------------------------------------------------


def take_screenshot() -> dict:
    """Capture a screenshot and save to the Desktop."""
    try:
        from PIL import ImageGrab
    except ImportError:
        return {
            "success": False,
            "message": "Screenshots require PIL (Pillow).",
        }

    try:
        screenshot = ImageGrab.grab()
        desktop = Path.home() / "Desktop"
        desktop.mkdir(exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"screenshot_{timestamp}.png"
        filepath = desktop / filename
        screenshot.save(str(filepath))
        return {
            "success": True,
            "message": f"Screenshot saved to {filepath}.",
            "details": {"filepath": str(filepath)},
        }
    except Exception as exc:
        return {
            "success": False,
            "message": f"Could not take screenshot: {exc}",
        }


# ---------------------------------------------------------------------------
# System commands
# ---------------------------------------------------------------------------


def lock_workstation() -> dict:
    """Lock the workstation."""
    try:
        subprocess.run(["rundll32.exe", "user32.dll,LockWorkStation"], timeout=5)
        return {"success": True, "message": "Workstation locked."}
    except Exception as exc:
        return {"success": False, "message": f"Could not lock workstation: {exc}"}


def shutdown_computer(delay_seconds: int = 5) -> dict:
    """Shut down the computer."""
    try:
        subprocess.run(["shutdown", "/s", "/t", str(delay_seconds)], timeout=5)
        return {"success": True, "message": f"Computer will shut down in {delay_seconds} seconds."}
    except Exception as exc:
        return {"success": False, "message": f"Could not initiate shutdown: {exc}"}


def restart_computer(delay_seconds: int = 5) -> dict:
    """Restart the computer."""
    try:
        subprocess.run(["shutdown", "/r", "/t", str(delay_seconds)], timeout=5)
        return {"success": True, "message": f"Computer will restart in {delay_seconds} seconds."}
    except Exception as exc:
        return {"success": False, "message": f"Could not initiate restart: {exc}"}


def sleep_computer() -> dict:
    """Put the computer to sleep."""
    try:
        subprocess.run(
            ["rundll32.exe", "powrprof.dll,SetSuspendState", "0", "1", "0"],
            timeout=5,
        )
        return {"success": True, "message": "Computer is going to sleep."}
    except Exception as exc:
        return {"success": False, "message": f"Could not sleep computer: {exc}"}
