"""
automation/mouse.py

Windows mouse automation via PyAutoGUI.
"""

from __future__ import annotations

from numbers import Real

import pyautogui


class MouseController:
    """Low-level mouse controller. Mutating methods return True/False."""

    def __init__(self) -> None:
        pyautogui.FAILSAFE = True

    @staticmethod
    def _coerce_int(value: object) -> int | None:
        if isinstance(value, bool) or not isinstance(value, Real):
            return None
        return int(value)

    @staticmethod
    def _coerce_duration(value: object, default: float) -> float:
        if isinstance(value, bool) or not isinstance(value, Real):
            return default
        return max(0.0, float(value))

    @staticmethod
    def _screen_size() -> tuple[int, int] | None:
        try:
            width, height = pyautogui.size()
            return int(width), int(height)
        except Exception:
            return None

    @classmethod
    def _in_bounds(cls, x: int, y: int) -> bool:
        size = cls._screen_size()
        if size is None:
            return False
        width, height = size
        return 0 <= x < width and 0 <= y < height

    def move_to(self, x: object, y: object, duration: object = 0.2) -> bool:
        """Move the cursor to absolute screen coordinates."""
        target_x = self._coerce_int(x)
        target_y = self._coerce_int(y)
        if target_x is None or target_y is None:
            return False
        if not self._in_bounds(target_x, target_y):
            return False

        try:
            pyautogui.moveTo(
                target_x,
                target_y,
                duration=self._coerce_duration(duration, 0.2),
            )
            return True
        except Exception:
            return False

    def move_relative(self, dx: object, dy: object, duration: object = 0.2) -> bool:
        """Move the cursor by dx/dy pixels relative to its current position."""
        delta_x = self._coerce_int(dx)
        delta_y = self._coerce_int(dy)
        if delta_x is None or delta_y is None:
            return False

        current_x, current_y = self.get_position()
        if current_x < 0 or current_y < 0:
            return False

        target_x = current_x + delta_x
        target_y = current_y + delta_y
        if not self._in_bounds(target_x, target_y):
            return False

        try:
            pyautogui.moveRel(
                delta_x,
                delta_y,
                duration=self._coerce_duration(duration, 0.2),
            )
            return True
        except Exception:
            return False

    def left_click(self) -> bool:
        """Left-click at the current cursor position."""
        try:
            pyautogui.click(button="left")
            return True
        except Exception:
            return False

    def right_click(self) -> bool:
        """Right-click at the current cursor position."""
        try:
            pyautogui.click(button="right")
            return True
        except Exception:
            return False

    def double_click(self) -> bool:
        """Double left-click at the current cursor position."""
        try:
            pyautogui.doubleClick(button="left")
            return True
        except Exception:
            return False

    def drag_to(self, x: object, y: object, duration: object = 0.5) -> bool:
        """Drag from the current cursor position to absolute coordinates."""
        target_x = self._coerce_int(x)
        target_y = self._coerce_int(y)
        if target_x is None or target_y is None:
            return False
        if not self._in_bounds(target_x, target_y):
            return False

        try:
            pyautogui.dragTo(
                target_x,
                target_y,
                duration=self._coerce_duration(duration, 0.5),
                button="left",
            )
            return True
        except Exception:
            return False

    def scroll(self, amount: object) -> bool:
        """Scroll the mouse wheel. Positive scrolls up; negative scrolls down."""
        scroll_amount = self._coerce_int(amount)
        if scroll_amount is None:
            return False
        if scroll_amount == 0:
            return True

        try:
            pyautogui.scroll(scroll_amount)
            return True
        except Exception:
            return False

    def get_position(self) -> tuple[int, int]:
        """Return the current cursor position, or (-1, -1) on failure."""
        try:
            position = pyautogui.position()
            return int(position.x), int(position.y)
        except Exception:
            return (-1, -1)

    def fail_safe(self, enable: bool) -> None:
        """Toggle PyAutoGUI's corner fail-safe."""
        pyautogui.FAILSAFE = bool(enable)
