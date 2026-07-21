"""
memory/vision_memory.py

Persistent memory for the Vision & Screen Understanding module.
Tracks screen capture history, located elements, and dialog state.
"""

from __future__ import annotations

import json
import logging
import os
import time
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_MEMORY_FILE = Path(__file__).resolve().parent / "vision_memory.json"


def _load() -> dict[str, Any]:
    if _MEMORY_FILE.exists():
        try:
            return json.loads(_MEMORY_FILE.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            pass
    return {
        "last_screen_ocr": "",
        "last_screen_timestamp": 0.0,
        "last_screen_resolution": "",
        "found_elements": {},
        "recent_dialogs": [],
        "max_dialogs": 20,
    }


def _save(data: dict[str, Any]) -> None:
    try:
        _MEMORY_FILE.write_text(
            json.dumps(data, indent=2, default=str),
            encoding="utf-8",
        )
    except OSError as exc:
        logger.warning("Could not write vision_memory.json: %s", exc)


def get_last_screen_text() -> str:
    return _load().get("last_screen_ocr", "")


def save_screen_text(text: str, resolution: str = "") -> None:
    data = _load()
    data["last_screen_ocr"] = text
    data["last_screen_timestamp"] = time.time()
    if resolution:
        data["last_screen_resolution"] = resolution
    _save(data)


def save_found_element(name: str, info: dict[str, Any]) -> None:
    data = _load()
    data["found_elements"][name] = {
        **info,
        "timestamp": time.time(),
    }
    _save(data)


def get_found_element(name: str) -> dict[str, Any] | None:
    return _load()["found_elements"].get(name)


def clear_found_elements() -> None:
    data = _load()
    data["found_elements"] = {}
    _save(data)


def save_dialog(text: str, is_error: bool = False) -> None:
    data = _load()
    entry = {
        "text": text,
        "is_error": is_error,
        "timestamp": time.time(),
    }
    data["recent_dialogs"].append(entry)
    max_d = data.get("max_dialogs", 20)
    if len(data["recent_dialogs"]) > max_d:
        data["recent_dialogs"] = data["recent_dialogs"][-max_d:]
    _save(data)


def get_recent_dialogs(count: int = 3) -> list[dict[str, Any]]:
    return _load()["recent_dialogs"][-count:]


def get_last_dialog() -> dict[str, Any] | None:
    dialogs = _load()["recent_dialogs"]
    return dialogs[-1] if dialogs else None
