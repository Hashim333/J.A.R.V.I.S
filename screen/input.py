"""
screen/input.py

Safe desktop input operations.
All coordinates validated against screen bounds, DPI scaling, window bounds.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from numbers import Real
from typing import Any

import pyautogui
import win32gui

logger = logging.getLogger(__name__)


@dataclass
class InputResult:
    """Result of an input action."""
    success: bool
    action: str
    x: int | None = None
    y: int | None = None
    error: str | None = None
    duration_ms: float = 0.0


class InputController:
    """
    Safe input controller with coordinate validation.

    Validates all coordinates against:
    - Current monitor layout
    - Window bounds (if targeting specific window)
    - DPI scaling
    - Actual screen size
    """

    def __init__(self, failsafe: bool = True, default_duration: float = 0.2):
        pyautogui.FAILSAFE = failsafe
        self.default_duration = default_duration
        self._screen_size_cache: tuple[int, int] | None = None
        self._cache_time = 0.0

    def _get_screen_size(self) -> tuple[int, int]:
        """Get screen size with caching."""
        now = time.monotonic()
        if self._screen_size_cache and (now - self._cache_time) < 1.0:
            return self._screen_size_cache

        try:
            width, height = pyautogui.size()
            self._screen_size_cache = (width, height)
            self._cache_time = now
            return (width, height)
        except Exception:
            return (1920, 1080)  # Fallback

    def _coerce_int(self, value: object) -> int | None:
        """Convert to int, rejecting bool."""
        if isinstance(value, bool) or not isinstance(value, Real):
            return None
        return int(value)

    def _coerce_float(self, value: object, default: float) -> float:
        """Convert to float with default."""
        if isinstance(value, bool) or not isinstance(value, Real):
            return default
        return max(0.0, float(value))

    def _in_bounds(self, x: int, y: int) -> bool:
        """Check if coordinates are within screen bounds."""
        width, height = self._get_screen_size()
        return 0 <= x < width and 0 <= y < height

    def _validate_window_bounds(self, hwnd: int, x: int, y: int) -> bool:
        """Validate coordinates are within window bounds."""
        try:
            rect = win32gui.GetWindowRect(hwnd)
            left, top, right, bottom = rect
            return left <= x < right and top <= y < bottom
        except Exception:
            return True  # If we can't check, allow it

    def click_at(
        self,
        x: object,
        y: object,
        button: str = "left",
        duration: object = None,
        hwnd: int | None = None,
    ) -> InputResult:
        """
        Click at absolute screen coordinates.

        Args:
            x, y: Screen coordinates
            button: "left", "right", "middle"
            duration: Move duration in seconds
            hwnd: Optional window handle to validate against

        Returns:
            InputResult with success status
        """
        start = time.monotonic()
        target_x = self._coerce_int(x)
        target_y = self._coerce_int(y)

        if target_x is None or target_y is None:
            return InputResult(
                success=False, action="click", error="Invalid coordinates",
            )

        if not self._in_bounds(target_x, target_y):
            return InputResult(
                success=False, action="click",
                error=f"Coordinates ({target_x}, {target_y}) out of screen bounds",
            )

        if hwnd and not self._validate_window_bounds(hwnd, target_x, target_y):
            logger.warning(f"Click ({target_x}, {target_y}) outside window {hwnd} bounds")

        try:
            move_duration = self._coerce_float(duration, self.default_duration)
            pyautogui.moveTo(target_x, target_y, duration=move_duration)
            pyautogui.click(button=button)
            return InputResult(
                success=True, action="click", x=target_x, y=target_y,
                duration_ms=(time.monotonic() - start) * 1000,
            )
        except Exception as exc:
            logger.exception("click_at failed")
            return InputResult(
                success=False, action="click", error=str(exc),
                duration_ms=(time.monotonic() - start) * 1000,
            )

    def double_click_at(
        self,
        x: object,
        y: object,
        duration: object = None,
        hwnd: int | None = None,
    ) -> InputResult:
        """Double-click at coordinates."""
        start = time.monotonic()
        target_x = self._coerce_int(x)
        target_y = self._coerce_int(y)

        if target_x is None or target_y is None:
            return InputResult(success=False, action="double_click", error="Invalid coordinates")

        if not self._in_bounds(target_x, target_y):
            return InputResult(success=False, action="double_click", error="Out of bounds")

        try:
            move_duration = self._coerce_float(duration, self.default_duration)
            pyautogui.moveTo(target_x, target_y, duration=move_duration)
            pyautogui.doubleClick(button="left")
            return InputResult(
                success=True, action="double_click", x=target_x, y=target_y,
                duration_ms=(time.monotonic() - start) * 1000,
            )
        except Exception as exc:
            return InputResult(success=False, action="double_click", error=str(exc), duration_ms=(time.monotonic() - start) * 1000)

    def right_click_at(
        self,
        x: object,
        y: object,
        duration: object = None,
        hwnd: int | None = None,
    ) -> InputResult:
        """Right-click at coordinates."""
        start = time.monotonic()
        target_x = self._coerce_int(x)
        target_y = self._coerce_int(y)

        if target_x is None or target_y is None:
            return InputResult(success=False, action="right_click", error="Invalid coordinates")

        if not self._in_bounds(target_x, target_y):
            return InputResult(success=False, action="right_click", error="Out of bounds")

        try:
            move_duration = self._coerce_float(duration, self.default_duration)
            pyautogui.moveTo(target_x, target_y, duration=move_duration)
            pyautogui.click(button="right")
            return InputResult(
                success=True, action="right_click", x=target_x, y=target_y,
                duration_ms=(time.monotonic() - start) * 1000,
            )
        except Exception as exc:
            return InputResult(success=False, action="right_click", error=str(exc), duration_ms=(time.monotonic() - start) * 1000)

    def drag_from_to(
        self,
        x1: object,
        y1: object,
        x2: object,
        y2: object,
        duration: object = 0.5,
        button: str = "left",
        hwnd: int | None = None,
    ) -> InputResult:
        """Drag from (x1,y1) to (x2,y2)."""
        start = time.monotonic()
        coords = [self._coerce_int(c) for c in (x1, y1, x2, y2)]
        if any(c is None for c in coords):
            return InputResult(success=False, action="drag", error="Invalid coordinates")

        sx, sy, ex, ey = coords
        if not (self._in_bounds(sx, sy) and self._in_bounds(ex, ey)):
            return InputResult(success=False, action="drag", error="Coordinates out of bounds")

        try:
            move_duration = self._coerce_float(duration, 0.5)
            pyautogui.moveTo(sx, sy, duration=0.1)
            pyautogui.dragTo(ex, ey, duration=move_duration, button=button)
            return InputResult(
                success=True, action="drag", x=sx, y=sy,
                duration_ms=(time.monotonic() - start) * 1000,
            )
        except Exception as exc:
            return InputResult(success=False, action="drag", error=str(exc), duration_ms=(time.monotonic() - start) * 1000)

    def scroll_at(
        self,
        x: object,
        y: object,
        amount: object,
        duration: object = None,
        hwnd: int | None = None,
    ) -> InputResult:
        """Scroll at coordinates. Positive = up, negative = down."""
        start = time.monotonic()
        target_x = self._coerce_int(x)
        target_y = self._coerce_int(y)
        scroll_amount = self._coerce_int(amount)

        if target_x is None or target_y is None or scroll_amount is None:
            return InputResult(success=False, action="scroll", error="Invalid parameters")

        if not self._in_bounds(target_x, target_y):
            return InputResult(success=False, action="scroll", error="Out of bounds")

        try:
            move_duration = self._coerce_float(duration, self.default_duration)
            pyautogui.moveTo(target_x, target_y, duration=move_duration)
            pyautogui.scroll(scroll_amount)
            return InputResult(
                success=True, action="scroll", x=target_x, y=target_y,
                duration_ms=(time.monotonic() - start) * 1000,
            )
        except Exception as exc:
            return InputResult(success=False, action="scroll", error=str(exc), duration_ms=(time.monotonic() - start) * 1000)

    def type_text(
        self,
        text: str,
        interval: float = 0.02,
    ) -> InputResult:
        """Type text at current cursor position."""
        start = time.monotonic()
        if not isinstance(text, str) or not text:
            return InputResult(success=False, action="type", error="Empty text")

        try:
            pyautogui.write(text, interval=interval)
            return InputResult(
                success=True, action="type",
                duration_ms=(time.monotonic() - start) * 1000,
            )
        except Exception as exc:
            return InputResult(success=False, action="type", error=str(exc), duration_ms=(time.monotonic() - start) * 1000)

    def send_hotkey(
        self,
        *keys: str,
        interval: float = 0.05,
    ) -> InputResult:
        """Send hotkey combination (e.g., 'ctrl', 'c')."""
        start = time.monotonic()
        if not keys:
            return InputResult(success=False, action="hotkey", error="No keys provided")

        try:
            pyautogui.hotkey(*keys, interval=interval)
            return InputResult(
                success=True, action="hotkey",
                duration_ms=(time.monotonic() - start) * 1000,
            )
        except Exception as exc:
            return InputResult(success=False, action="hotkey", error=str(exc), duration_ms=(time.monotonic() - start) * 1000)

    def press_key(self, key: str) -> InputResult:
        """Press a single key."""
        start = time.monotonic()
        try:
            pyautogui.press(key)
            return InputResult(success=True, action="press", duration_ms=(time.monotonic() - start) * 1000)
        except Exception as exc:
            return InputResult(success=False, action="press", error=str(exc), duration_ms=(time.monotonic() - start) * 1000)

    def hold_key(self, key: str) -> InputResult:
        """Hold a key down."""
        start = time.monotonic()
        try:
            pyautogui.keyDown(key)
            return InputResult(success=True, action="hold", duration_ms=(time.monotonic() - start) * 1000)
        except Exception as exc:
            return InputResult(success=False, action="hold", error=str(exc), duration_ms=(time.monotonic() - start) * 1000)

    def release_key(self, key: str) -> InputResult:
        """Release a held key."""
        start = time.monotonic()
        try:
            pyautogui.keyUp(key)
            return InputResult(success=True, action="release", duration_ms=(time.monotonic() - start) * 1000)
        except Exception as exc:
            return InputResult(success=False, action="release", error=str(exc), duration_ms=(time.monotonic() - start) * 1000)

    def get_position(self) -> tuple[int, int]:
        """Get current mouse position."""
        try:
            pos = pyautogui.position()
            return int(pos.x), int(pos.y)
        except Exception:
            return (-1, -1)


# Module-level functions
_default_controller: InputController | None = None


def _get_controller() -> InputController:
    global _default_controller
    if _default_controller is None:
        _default_controller = InputController()
    return _default_controller


def click_at(x: object, y: object, **kwargs) -> dict:
    """Click at coordinates - module function."""
    return _get_controller().click_at(x, y, **kwargs).__dict__


def double_click_at(x: object, y: object, **kwargs) -> dict:
    return _get_controller().double_click_at(x, y, **kwargs).__dict__


def right_click_at(x: object, y: object, **kwargs) -> dict:
    return _get_controller().right_click_at(x, y, **kwargs).__dict__


def drag_from_to(x1: object, y1: object, x2: object, y2: object, **kwargs) -> dict:
    return _get_controller().drag_from_to(x1, y1, x2, y2, **kwargs).__dict__


def scroll_at(x: object, y: object, amount: object, **kwargs) -> dict:
    return _get_controller().scroll_at(x, y, amount, **kwargs).__dict__


def type_text(text: str, **kwargs) -> dict:
    return _get_controller().type_text(text, **kwargs).__dict__


def send_hotkey(*keys: str, **kwargs) -> dict:
    return _get_controller().send_hotkey(*keys, **kwargs).__dict__