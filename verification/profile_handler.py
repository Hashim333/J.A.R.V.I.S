from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from context_manager.app_detector import AppDetector
from models.response import Response

logger = logging.getLogger(__name__)


@dataclass
class ChromeProfile:
    directory: str
    display_name: str


class ChromeProfileHandler:
    def __init__(
        self,
        app_detector: AppDetector | None = None,
    ) -> None:
        self._app_detector = app_detector or AppDetector()
        self._pending: dict[str, Any] | None = None

    def handle_chrome_picker(
        self,
        display_name: str,
        entities: dict[str, Any],
    ) -> Response:
        profiles = self._discover_chrome_profiles()
        app_name = entities.get("app_name", "chrome")

        if not profiles:
            return Response(
                success=True,
                message=f"{display_name} opened.",
            )

        if len(profiles) == 1:
            return self._auto_select_profile(profiles[0], display_name, entities)

        names = [p.display_name for p in profiles]
        self._pending = {
            "check_type": "chrome_profile",
            "profiles": profiles,
            "display_name": display_name,
            "entities": entities,
            "app_name": app_name,
        }

        question = f"I found these profiles: {' | '.join(names)}. Which one would you like to open?"
        return Response(
            success=False,
            message=question,
            needs_clarification=True,
            clarification_question=question,
            data={"app_name": app_name, "profiles": names},
        )

    def resolve_profile(self, answer: str, pending: dict[str, Any]) -> Response | None:
        profiles = pending.get("profiles", [])
        display_name = pending.get("display_name", "")
        entities = pending.get("entities", {})

        selected = self._match_profile(answer, profiles)
        if selected is None:
            names = [p.display_name for p in profiles]
            question = f"I didn't catch that. The available profiles are: {' | '.join(names)}. Which one would you like?"
            self._pending["retry_count"] = self._pending.get("retry_count", 0) + 1
            if self._pending["retry_count"] >= 3:
                self._pending = None
                return Response(
                    success=True,
                    message=f"{display_name} opened. Please select your profile manually.",
                )
            return Response(
                success=False,
                message=question,
                needs_clarification=True,
                clarification_question=question,
                data={"app_name": entities.get("app_name", ""), "profiles": names},
            )

        self._pending = None
        return self._auto_select_profile(selected, display_name, entities)

    def _auto_select_profile(
        self,
        profile: ChromeProfile,
        display_name: str,
        entities: dict[str, Any],
    ) -> Response:
        directory = profile.directory
        executable = self._find_chrome_executable()
        if executable and directory:
            import subprocess
            try:
                subprocess.Popen(
                    [executable, f"--profile-directory={directory}"],
                    shell=False,
                )
            except OSError as exc:
                logger.warning("Failed to re-launch Chrome with profile: %s", exc)
                return Response(
                    success=True,
                    message=f"{display_name} opened. Please select your profile.",
                )

        return Response(
            success=True,
            message=f"Opened {display_name} with {profile.display_name} profile.",
            data={"profile": profile.display_name},
        )

    def _match_profile(self, answer: str, profiles: list[ChromeProfile]) -> ChromeProfile | None:
        answer_lower = answer.strip().casefold()
        if not answer_lower:
            return None

        for p in profiles:
            if p.display_name.casefold() == answer_lower:
                return p

        for p in profiles:
            if answer_lower in p.display_name.casefold():
                return p

        from voice.selection_manager import _parse_index as parse_index
        idx = parse_index(answer_lower)
        if idx is not None and 0 <= idx < len(profiles):
            return profiles[idx]

        words = answer_lower.split()
        for p in profiles:
            name_lower = p.display_name.casefold()
            if all(w in name_lower for w in words):
                return p

        return None

    def _discover_chrome_profiles(self) -> list[ChromeProfile]:
        user_data = self._find_chrome_user_data()
        if not user_data:
            return []

        local_state_path = user_data / "Local State"
        if not local_state_path.exists():
            return []

        try:
            with local_state_path.open("r", encoding="utf-8") as f:
                local_state = json.load(f)
        except (json.JSONDecodeError, OSError) as exc:
            logger.debug("Could not read Chrome Local State: %s", exc)
            return []

        info_cache = local_state.get("profile", {}).get("info_cache", {})
        if not isinstance(info_cache, dict):
            return []

        profiles: list[ChromeProfile] = []
        for directory, data in info_cache.items():
            if not isinstance(directory, str):
                continue
            if not isinstance(data, dict):
                data = {}
            name = data.get("name") or data.get("shortcut_name") or data.get("gaia_name") or directory
            profiles.append(ChromeProfile(directory=directory, display_name=str(name)))

        seen: set[str] = set()
        unique: list[ChromeProfile] = []
        for p in profiles:
            key = p.display_name.casefold()
            if key not in seen:
                seen.add(key)
                unique.append(p)

        return unique

    def _find_chrome_user_data(self) -> Path | None:
        candidates = [
            Path(os.environ.get("LOCALAPPDATA", "")) / "Google" / "Chrome" / "User Data",
            Path(os.environ.get("USERPROFILE", "")) / "AppData" / "Local" / "Google" / "Chrome" / "User Data",
        ]
        for c in candidates:
            if c.exists():
                return c
        return None

    def _find_chrome_executable(self) -> str | None:
        candidates = [
            Path(os.environ.get("ProgramFiles", "")) / "Google" / "Chrome" / "Application" / "chrome.exe",
            Path(os.environ.get("ProgramFiles(x86)", "")) / "Google" / "Chrome" / "Application" / "chrome.exe",
            Path(os.environ.get("LOCALAPPDATA", "")) / "Google" / "Chrome" / "Application" / "chrome.exe",
        ]
        for c in candidates:
            if c.exists():
                return str(c)
        return None
