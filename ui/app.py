"""
ui/app.py

JARVIS Desktop Shell — entry point.
Creates the QApplication, system tray, bridge, window manager, loads the
web-based UI (HTML/CSS/JS) in a QWebEngineView, and coordinates window
mode transitions.
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

from PySide6.QtCore import QUrl, Qt, QObject, QSize
from PySide6.QtGui import QIcon, QPixmap, QPainter, QSurfaceFormat, QAction
from PySide6.QtWidgets import QApplication, QSystemTrayIcon, QMenu
from PySide6.QtQml import QQmlApplicationEngine

from ui.bridge import Bridge
from ui.window_manager import WindowManager

logger = logging.getLogger(__name__)


class JarvisApp:
    """Top-level application controller for the JARVIS desktop shell."""

    def __init__(self) -> None:
        existing = QApplication.instance()
        if existing is not None:
            self.app = existing
        else:
            self.app = QApplication(sys.argv)
        self.app.setApplicationName("JARVIS")
        self.app.setOrganizationName("JARVIS")
        self.app.setQuitOnLastWindowClosed(False)

        fmt = QSurfaceFormat()
        fmt.setSamples(4)
        fmt.setSwapInterval(1)
        QSurfaceFormat.setDefaultFormat(fmt)

        self.bridge = Bridge()
        self.wm = WindowManager(self.bridge)
        self.tray: QSystemTrayIcon | None = None
        self._tray_icon: QPixmap | None = None

        self._setup_tray()
        self._wire_bridge()
        self._create_window()
        self.wm.start()

    # ── Tray ──────────────────────────────────────────────────────────

    def _setup_tray(self) -> None:
        if not QSystemTrayIcon.isSystemTrayAvailable():
            logger.info("System tray not available")
            return

        self._tray_icon = self._make_tray_pixmap(22)

        self.tray = QSystemTrayIcon()
        self.tray.setIcon(QIcon(self._tray_icon))
        self.tray.setToolTip("JARVIS")

        menu = QMenu()

        show_action = QAction("Show JARVIS")
        show_action.triggered.connect(self._tray_show)
        menu.addAction(show_action)

        orb_action = QAction("Floating Orb")
        orb_action.triggered.connect(self._tray_orb)
        menu.addAction(orb_action)

        menu.addSeparator()

        quit_action = QAction("Quit")
        quit_action.triggered.connect(self._quit)
        menu.addAction(quit_action)

        self.tray.setContextMenu(menu)

        self.tray.activated.connect(self._tray_activated)
        self.tray.show()

    def _make_tray_pixmap(self, size: int) -> QPixmap:
        pix = QPixmap(size, size)
        pix.fill(Qt.transparent)
        from PySide6.QtGui import QBrush, QColor
        p = QPainter(pix)
        p.setRenderHint(QPainter.Antialiasing)
        p.setBrush(QBrush(QColor("#ff7b00")))
        p.setPen(Qt.NoPen)
        p.drawEllipse(1, 1, size - 2, size - 2)
        p.end()
        return pix

    def _tray_activated(self, reason: int) -> None:
        if reason == QSystemTrayIcon.DoubleClick:
            self.wm.set_mode("fullscreen")
        elif reason == QSystemTrayIcon.Trigger:
            self.wm.set_mode("floating_orb")

    def _tray_show(self) -> None:
        self.wm.set_mode("fullscreen")

    def _tray_orb(self) -> None:
        self.wm.set_mode("floating_orb")

    # ── Bridge wiring ─────────────────────────────────────────────────

    def _wire_bridge(self) -> None:
        self.wm.modeChanged.connect(self.bridge.set_window_mode)
        self.bridge.windowModeChanged.connect(self.wm.set_mode)
        self.bridge.minimizeRequested.connect(self._minimize_window)

    # ── Window / QML UI ──────────────────────────────────────────────

    def _create_window(self) -> None:
        self._engine = QQmlApplicationEngine()
        self._engine.rootContext().setContextProperty("bridge", self.bridge)

        qml_path = Path(__file__).parent / "qml" / "v4_deprecated" / "MainWindow.qml"
        self._engine.load(QUrl.fromLocalFile(str(qml_path)))

        root_objects = self._engine.rootObjects()
        if not root_objects:
            logger.critical("No QML root objects loaded — UI will not be visible")
            return

        self.window = root_objects[0]
        self.window.setMinimumSize(QSize(1280, 720))

        # Force WS_EX_APPWINDOW so the frameless window has a taskbar button
        self._ensure_taskbar_icon()
        self.window.showMaximized()

        self.wm.set_fullscreen_window(self.window)

    def _ensure_taskbar_icon(self) -> None:
        """Apply WS_EX_APPWINDOW extended style for proper taskbar integration."""
        try:
            import ctypes
            from ctypes import wintypes
            hwnd = int(self.window.winId())
            GWL_EXSTYLE = -20
            WS_EX_APPWINDOW = 0x00040000
            user32 = ctypes.windll.user32
            current = user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
            if current & WS_EX_APPWINDOW:
                return
            user32.SetWindowLongW(hwnd, GWL_EXSTYLE, current | WS_EX_APPWINDOW)
            user32.SetWindowPos(hwnd, 0, 0, 0, 0, 0, 0x0020 | 0x0002 | 0x0004 | 0x0001)
            logger.info("Applied WS_EX_APPWINDOW for taskbar integration")
        except Exception as exc:
            logger.warning("Failed to set WS_EX_APPWINDOW: %s", exc)

    # ── Window minimize ───────────────────────────────────────────────

    def _minimize_window(self) -> None:
        if not hasattr(self, 'window') or self.window is None:
            return
        try:
            import ctypes
            hwnd = int(self.window.winId())
            SW_MINIMIZE = 6
            ctypes.windll.user32.ShowWindow(hwnd, SW_MINIMIZE)
            self.window.setWindowState(self.window.windowState() | Qt.WindowMinimized)
        except Exception as exc:
            logger.warning("WinAPI minimize failed, falling back to Qt: %s", exc)
            self.window.showMinimized()

    # ── Run ───────────────────────────────────────────────────────────

    def run(self) -> int:
        logger.info("JARVIS UI starting")
        return self.app.exec()

    def _quit(self) -> None:
        logger.info("JARVIS UI shutting down")
        self.app.quit()
