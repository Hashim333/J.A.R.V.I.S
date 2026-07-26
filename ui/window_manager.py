"""
ui/window_manager.py

Manages window modes (fullscreen, floating orb, edge dock, system tray)
and auto-behavior (detect foreground app, gaming, fullscreen video).
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Callable

from PySide6.QtCore import QObject, Signal, QTimer
from PySide6.QtGui import QWindow, QScreen
from PySide6.QtWidgets import QApplication

logger = logging.getLogger(__name__)


class WindowManager(QObject):
    """Coordinates window mode transitions and auto-behavior."""

    modeChanged = Signal(str)

    def __init__(self, bridge: object, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._bridge = bridge
        self._current_mode = "fullscreen"
        self._previous_mode = "fullscreen"
        self._fullscreen_window: QWindow | None = None
        self._orb_window: QWindow | None = None
        self._dock_window: QWindow | None = None
        self._own_window_hwnd: int | None = None
        self._callbacks: dict[str, list[Callable]] = {
            "enter_fullscreen": [],
            "enter_orb": [],
            "enter_dock": [],
            "enter_tray": [],
            "exit_fullscreen": [],
            "exit_orb": [],
            "exit_dock": [],
            "exit_tray": [],
        }

        # Poll timer created but NOT started here — call start() after QML loads
        self._poll_timer = QTimer(self)
        self._poll_timer.timeout.connect(self._poll_foreground)

    # ── Mode management ───────────────────────────────────────────────

    @property
    def current_mode(self) -> str:
        return self._current_mode

    def set_mode(self, mode: str) -> None:
        if mode == self._current_mode:
            return
        self._previous_mode = self._current_mode
        self._current_mode = mode

        self._fire(f"exit_{self._previous_mode}")
        self._fire(f"enter_{mode}")

        self.modeChanged.emit(mode)
        logger.info("WindowManager: %s → %s", self._previous_mode, mode)

    def toggle_mode(self, mode: str) -> None:
        if self._current_mode == mode:
            self.set_mode(self._previous_mode)
        else:
            self.set_mode(mode)

    # ── Startup (call after QML is loaded) ────────────────────────────

    def start(self) -> None:
        """Begin foreground polling after a 3 s startup delay."""
        QTimer.singleShot(3000, lambda: self._poll_timer.start(2000))

    # ── Window references (set by app.py after QML loads) ─────────────

    def set_fullscreen_window(self, w: QWindow | None) -> None:
        self._fullscreen_window = w
        if w is not None:
            try:
                self._own_window_hwnd = int(w.winId())
            except Exception:
                self._own_window_hwnd = None

    def set_orb_window(self, w: QWindow | None) -> None:
        self._orb_window = w

    def set_dock_window(self, w: QWindow | None) -> None:
        self._dock_window = w

    # ── Callbacks for mode transitions ────────────────────────────────

    def on(self, event: str, cb: Callable) -> None:
        if event in self._callbacks:
            self._callbacks[event].append(cb)

    def _fire(self, event: str) -> None:
        for cb in self._callbacks.get(event, []):
            try:
                cb()
            except Exception as exc:
                logger.warning("WindowManager: callback error %s: %s", event, exc)

    # ── Auto-behavior ─────────────────────────────────────────────────

    def _poll_foreground(self) -> None:
        """Check foreground app and adjust mode if needed."""
        try:
            import ctypes
            user32 = ctypes.windll.user32
            hwnd = user32.GetForegroundWindow()
            if not hwnd:
                return

            # Skip if it is our own fullscreen window
            if self._own_window_hwnd is not None and hwnd == self._own_window_hwnd:
                return

            length = user32.GetWindowTextLengthW(hwnd) + 1
            buf = ctypes.create_unicode_buffer(length)
            user32.GetWindowTextW(hwnd, buf, length)
            title = buf.value.strip().lower() if buf.value else ""

            # Detect full-screen / gaming
            is_fullscreen_app = self._detect_fullscreen(hwnd)
            is_desktop = title in ("", "program manager", "windows shell experience")

            if self._current_mode == "fullscreen":
                if is_fullscreen_app:
                    logger.info("WManager: fullscreen app detected → orb")
                    self.set_mode("floating_orb")
            elif self._current_mode == "floating_orb":
                if is_desktop:
                    logger.info("WManager: desktop active → fullscreen")
                    self.set_mode("fullscreen")
        except Exception:
            pass

    def _detect_fullscreen(self, hwnd: int) -> bool:
        """Heuristic: window covers entire workspace."""
        try:
            import ctypes
            user32 = ctypes.windll.user32

            r = ctypes.wintypes.RECT()
            user32.GetWindowRect(hwnd, ctypes.byref(r))
            w = r.right - r.left
            h = r.bottom - r.top

            screen = QApplication.primaryScreen()
            if screen:
                geo = screen.availableGeometry()
                return w >= geo.width() and h >= geo.height()
        except Exception:
            pass
        return False
