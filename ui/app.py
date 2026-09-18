"""
ui/app.py

JARVIS Desktop Shell — entry point and shutdown coordinator.

Thread model
------------
- **Qt MainThread** runs the Qt event loop, Bridge signal handlers, and
  QML property updates.
- **system-monitor** daemon thread polls CPU/RAM/GPU/Disk/Battery via
  psutil/WMI and sends results to Bridge via auto-queued Qt signals.
- **world-model** daemon thread drives domain-specific collectors.
- **working-memory** daemon thread evicts expired entries every 60s.
- All background threads receive a ``threading.Event`` stop signal and
  are joined with a timeout during shutdown.

Shutdown sequence
-----------------
1. SystemMonitor.stop()     → signal, join (5s timeout)
2. WorldModel.stop()        → signal, join (5s timeout)
3. WorkingMemory.stop()     → signal, join (5s timeout)
4. app.quit()               → QCoreApplication::quit()

Each step is timed and failures are logged.
"""

from __future__ import annotations

import logging
import sys
import time
from pathlib import Path

from PySide6.QtCore import QUrl, Qt, QObject, QSize
from PySide6.QtGui import QIcon, QPixmap, QPainter, QSurfaceFormat, QAction
from PySide6.QtWidgets import QApplication, QWidget, QSystemTrayIcon, QMenu
from PySide6.QtQml import QQmlApplicationEngine

from ui.bridge import Bridge
from ui.system_monitor import SystemMonitor
from ui.window_manager import WindowManager

logger = logging.getLogger(__name__)


class JarvisApp:
    """Top-level application controller for the JARVIS desktop shell.

    Owns the shutdown sequence for all background services.
    """

    def __init__(self) -> None:
        existing = QApplication.instance()
        if existing is not None:
            self.app = existing
        else:
            self.app = QApplication(sys.argv)
        self.app.setApplicationName("JARVIS")
        self.app.setOrganizationName("JARVIS")
        self.app.setQuitOnLastWindowClosed(False)

        # Application icon (taskbar / alt-tab / window title bar).
        # Drawn programmatically — the orange orb is the JARVIS brand mark.
        self._app_icon = QIcon(self._make_tray_pixmap(256))
        self.app.setWindowIcon(self._app_icon)

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

        self._monitor = SystemMonitor(self.bridge)
        self._monitor.start()

        self._world_model = None
        self._working_memory = None

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

        # Lightweight presentation shell (replaces the heavy v4 dashboard;
        # v4_deprecated/ is retained off-path for reference).  Backend and
        # bridge contract are unchanged — the shell only renders
        # bridge.coreState / subtitle signals.
        qml_path = Path(__file__).parent / "qml" / "light" / "Shell.qml"
        self._engine.load(QUrl.fromLocalFile(str(qml_path)))

        root_objects = self._engine.rootObjects()
        if not root_objects:
            logger.critical("No QML root objects loaded — UI will not be visible")
            return

        self.window = root_objects[0]
        self.window.setMinimumSize(QSize(480, 320))

        # The QML top-level window is a QWindow (on Windows). QWindow has no
        # setWindowIcon() — that is a QWidget-only API. The icon is provided
        # process-wide via QApplication.setWindowIcon() plus (on Windows) the
        # native AppUserModelID association in _apply_windows_taskbar_identity().
        if isinstance(self.window, QWidget):
            self.window.setWindowIcon(self._app_icon)
        else:
            self._apply_windows_taskbar_identity()

        # Force WS_EX_APPWINDOW so the frameless window has a taskbar button
        self._ensure_taskbar_icon()
        self.window.showNormal()

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

    def _apply_windows_taskbar_identity(self) -> None:
        """Associate the process with a Windows AppUserModelID.

        On Windows, the taskbar groups and icons windows by AppUserModelID.
        Without an explicit ID, a QML top-level window (QWindow) shows the
        default Python/blank taskbar icon regardless of
        QApplication.setWindowIcon(). Setting an explicit process-level ID
        makes the taskbar use the QApplication icon.

        Uses the native Win32 API — QWindow does not expose setWindowIcon()
        (that is a QWidget-only API), so this is the correct mechanism for a
        QML-based window.
        """
        if sys.platform != "win32":
            return
        try:
            import ctypes
            shell32 = ctypes.windll.shell32
            proc = getattr(
                shell32, "SetCurrentProcessExplicitAppUserModelID", None
            )
            if proc is None:
                logger.debug("AppUserModelID API not available")
                return
            proc.argtypes = [ctypes.c_wchar_p]
            proc.restype = ctypes.c_long
            hr = proc("JARVIS.Desktop")
            logger.info("Set Windows AppUserModelID (hr=0x%08x)", hr)
        except Exception as exc:
            logger.warning("Failed to set AppUserModelID: %s", exc)

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
        logger.info("JARVIS UI: Qt event loop starting")
        return self.app.exec()

    def _quit(self) -> None:
        logger.info("JARVIS UI: shutdown started")
        shutdown_start = time.monotonic()

        # Stop timers first to prevent re-entrant calls during shutdown
        self.bridge.stop_timers()
        self.wm.stop_timers()

        self._stop_service(
            "SystemMonitor", self._monitor.stop,
            lambda: self._monitor is not None,
        )

        if self._world_model is not None:
            self._stop_service("WorldModel", self._world_model.stop)

        if self._working_memory is not None:
            self._stop_service("WorkingMemory", self._working_memory.stop)

        total_ms = (time.monotonic() - shutdown_start) * 1000
        logger.info("JARVIS UI: shutdown complete in %.0fms", total_ms)

        from PySide6.QtCore import QCoreApplication
        QCoreApplication.quit()

    @staticmethod
    def _stop_service(
        name: str, stop_fn, guard=None, timeout: float = 5.0,
    ) -> None:
        """Signal a background service to stop and wait for its thread.

        Logs start, duration, and any failure to stop within *timeout*.
        """
        if guard is not None and not guard():
            logger.debug("JARVIS: %s not running — skipped", name)
            return
        start = time.monotonic()
        try:
            stop_fn()
        except Exception as exc:
            logger.error(
                "JARVIS: %s.stop() raised %s: %s",
                name, type(exc).__name__, exc,
            )
            return
        elapsed = (time.monotonic() - start) * 1000
        if elapsed >= timeout * 1000:
            logger.warning(
                "JARVIS: %s stop took %.0fms (may have timed out)",
                name, elapsed,
            )
        else:
            logger.info(
                "JARVIS: %s stopped in %.0fms", name, elapsed,
            )
