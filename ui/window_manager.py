"""Owns visibility actions for the desktop window."""
from __future__ import annotations

from PySide6.QtCore import QObject, Qt, Slot
from PySide6.QtWidgets import QWidget


class WindowManager(QObject):
    """Routes Bridge show/hide requests to the current window."""

    def __init__(self, bridge: QObject, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._window: QWidget | None = None
        bridge.showRequested.connect(
            self.show_window, Qt.ConnectionType.QueuedConnection,
        )
        bridge.hideRequested.connect(
            self.hide_window, Qt.ConnectionType.QueuedConnection,
        )

    def set_window(self, window: QWidget) -> None:
        self._window = window

    @Slot()
    def show_window(self) -> None:
        if self._window is not None:
            self._window.showNormal()
            self._window.raise_()
            self._window.activateWindow()

    @Slot()
    def hide_window(self) -> None:
        if self._window is not None:
            self._window.hide()
