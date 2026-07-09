"""
automation/apps.py

Windows desktop application launch/status helpers.

This module only launches, closes, and checks supported applications. It
does not parse text, build plans, call an LLM, or automate browser pages.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path

import psutil


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


def _normalize_name(name: str) -> str:
    if not isinstance(name, str) or not name.strip():
        raise AppOperationError("Application name must be a non-empty string.")

    key = name.strip().casefold()
    aliases = {
        "calc": "calculator",
        "google chrome": "chrome",
        "microsoft edge": "edge",
        "ms edge": "edge",
        "code": "vscode",
        "vs code": "vscode",
        "visual studio code": "vscode",
        "mspaint": "paint",
    }
    return aliases.get(key, key)


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
    }


def _app_spec(name: str) -> _AppSpec:
    key = _normalize_name(name)
    specs = _app_specs()
    try:
        return specs[key]
    except KeyError:
        raise AppOperationError(
            f"Unsupported application {name!r}. Supported applications are: "
            f"{', '.join(sorted(specs))}."
        ) from None


def _resolve_launch_candidates(name: str) -> list[str]:
    spec = _app_spec(name)
    checked: list[str] = []
    resolved: list[str] = []

    for candidate in spec.candidates:
        if isinstance(candidate, Path):
            checked.append(str(candidate))
            if candidate.exists():
                resolved.append(str(candidate))
            continue

        checked.append(candidate)
        path_match = shutil.which(candidate)
        if path_match:
            resolved.append(path_match)

    if resolved:
        return resolved

    raise AppNotFoundError(
        f"Could not find an executable for {name!r}. Checked: {', '.join(checked)}."
    )


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
        f"{', '.join(str(candidate) for candidate in candidates)}."
    )


def _chrome_profiles() -> list[_ChromeProfile]:
    local_state_path = _chrome_user_data_dir() / "Local State"
    if not local_state_path.exists():
        raise AppOperationError(
            f"Could not find Chrome Local State file at {local_state_path}."
        )

    try:
        with local_state_path.open("r", encoding="utf-8") as file:
            local_state = json.load(file)
    except json.JSONDecodeError as exc:
        raise AppOperationError(
            f"Chrome Local State file is not valid JSON: {local_state_path}."
        ) from exc
    except OSError as exc:
        raise AppOperationError(
            f"Could not read Chrome Local State file: {local_state_path}."
        ) from exc

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
        profiles.append(
            _ChromeProfile(directory=directory, display_name=str(display_name))
        )

    if not profiles:
        raise AppOperationError("No usable Chrome profiles were found in Local State.")

    return profiles


def _select_chrome_profile(profiles: list[_ChromeProfile]) -> _ChromeProfile:
    if len(profiles) == 1:
        return profiles[0]

    print("Which Chrome profile would you like to open?")
    for index, profile in enumerate(profiles, start=1):
        print(f"{index}. {profile.display_name}")

    profile_names: dict[str, _ChromeProfile] = {}
    for profile in profiles:
        profile_names.setdefault(profile.display_name.casefold(), profile)

    while True:
        choice = input("Chrome profile: ").strip()
        if choice.isdigit():
            profile_number = int(choice)
            if 1 <= profile_number <= len(profiles):
                return profiles[profile_number - 1]

        selected_profile = profile_names.get(choice.casefold())
        if selected_profile is not None:
            return selected_profile

        print("Invalid Chrome profile. Enter a profile number or display name.")


def _popen(command: list[str]) -> None:
    subprocess.Popen(
        command,
        shell=False,
        creationflags=subprocess.CREATE_NEW_PROCESS_GROUP,
    )


def _launch(name: str, extra_args: list[str] | None = None) -> bool:
    errors: list[str] = []
    extra_args = extra_args or []

    for executable in _resolve_launch_candidates(name):
        command = [executable, *extra_args]
        try:
            _popen(command)
        except FileNotFoundError as exc:
            errors.append(f"{executable!r}: not found ({exc})")
            continue
        except OSError as exc:
            errors.append(f"{executable!r}: {exc}")
            continue

        time.sleep(0.5)
        return True

    raise AppOperationError(
        f"Could not launch {name!r}. Tried: {'; '.join(errors)}."
    )


def _open_chrome() -> bool:
    profile = _select_chrome_profile(_chrome_profiles())
    return _launch("chrome", [f"--profile-directory={profile.directory}"])


def _process_name_for(name: str) -> str:
    return _app_spec(name).process_name


def _matches_process(proc: psutil.Process, process_name: str) -> bool:
    try:
        return proc.name().casefold() == process_name.casefold()
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        return False


def is_running(name: str) -> bool:
    """Return True when the supported application has a running process."""
    process_name = _process_name_for(name)

    try:
        return any(
            _matches_process(proc, process_name)
            for proc in psutil.process_iter(["name"])
        )
    except Exception as exc:
        raise AppOperationError(f"Failed to query running processes: {exc}") from exc


def open_app(name: str) -> bool:
    """Launch a supported Windows desktop application."""
    if sys.platform != "win32":
        raise AppOperationError(_WINDOWS_ONLY_MESSAGE)

    if _normalize_name(name) == "chrome":
        return _open_chrome()

    return _launch(name)


def close_app(name: str) -> bool:
    """Terminate running processes for a supported application."""
    if sys.platform != "win32":
        raise AppOperationError(_WINDOWS_ONLY_MESSAGE)

    process_name = _process_name_for(name)
    terminated_any = False

    try:
        for proc in psutil.process_iter(["name"]):
            if _matches_process(proc, process_name):
                proc.terminate()
                terminated_any = True
    except Exception as exc:
        raise AppOperationError(f"Failed to close {process_name!r}: {exc}") from exc

    if not terminated_any:
        raise AppOperationError(f"No running process found for {name!r}.")

    return True
