"""
automation/keyboard.py

Windows keyboard automation via PyAutoGUI.
"""

from __future__ import annotations

from collections.abc import Iterable

import pyautogui


class KeyboardController:
    """Low-level keyboard controller. Mutating methods return True/False."""

    @staticmethod
    def _normalize_key(key: object) -> str | None:
        if not isinstance(key, str):
            return None

        normalized = key.strip().lower()
        if not normalized:
            return None

        aliases = {
            "esc": "escape",
            "return": "enter",
            "ctrl": "ctrl",
            "control": "ctrl",
            "del": "delete",
            "bksp": "backspace",
            "spacebar": "space",
            "win": "win",
            "windows": "win",
        }
        normalized = aliases.get(normalized, normalized)

        if normalized not in pyautogui.KEYBOARD_KEYS:
            return None
        return normalized

    @classmethod
    def _normalize_keys(cls, keys: object) -> tuple[str, ...] | None:
        if isinstance(keys, str):
            split_keys = [part.strip() for part in keys.replace("+", ",").split(",")]
            raw_keys: Iterable[object] = split_keys
        elif isinstance(keys, Iterable):
            raw_keys = keys
        else:
            return None

        normalized: list[str] = []
        for key in raw_keys:
            normalized_key = cls._normalize_key(key)
            if normalized_key is None:
                return None
            normalized.append(normalized_key)

        return tuple(normalized) if normalized else None

    def type_text(self, text: object) -> bool:
        """Type text at the current input focus."""
        if not isinstance(text, str) or not text:
            return False

        try:
            pyautogui.write(text, interval=0.03)
            return True
        except Exception:
            return False

    def press(self, key: object) -> bool:
        """Press and release one key."""
        normalized_key = self._normalize_key(key)
        if normalized_key is None:
            return False

        try:
            pyautogui.press(normalized_key)
            return True
        except Exception:
            return False

    def hotkey(self, *keys: object) -> bool:
        """Press a key combination."""
        normalized_keys = self._normalize_keys(keys)
        if normalized_keys is None:
            return False

        try:
            pyautogui.hotkey(*normalized_keys)
            return True
        except Exception:
            return False

    def hold(self, key: object) -> bool:
        """Press and hold one key."""
        normalized_key = self._normalize_key(key)
        if normalized_key is None:
            return False

        try:
            pyautogui.keyDown(normalized_key)
            return True
        except Exception:
            return False

    def release(self, key: object) -> bool:
        """Release one key."""
        normalized_key = self._normalize_key(key)
        if normalized_key is None:
            return False

        try:
            pyautogui.keyUp(normalized_key)
            return True
        except Exception:
            return False

    def enter(self) -> bool:
        """Press Enter."""
        return self.press("enter")

    def tab(self) -> bool:
        """Press Tab."""
        return self.press("tab")

    def escape(self) -> bool:
        """Press Escape."""
        return self.press("escape")

    def backspace(self) -> bool:
        """Press Backspace."""
        return self.press("backspace")
