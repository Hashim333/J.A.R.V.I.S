"""Qt Widgets shell, tray, and application shutdown."""
from __future__ import annotations

import logging
import sys
from pathlib import Path

from PySide6.QtCore import QTimer, Qt, QUrl
from PySide6.QtGui import QAction, QIcon, QPainter, QPixmap
from PySide6.QtNetwork import QLocalServer, QLocalSocket
from PySide6.QtWebChannel import QWebChannel
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWidgets import QApplication, QLabel, QMainWindow, QMenu, QSystemTrayIcon

from ui.bridge import Bridge
from ui.window_manager import WindowManager

logger = logging.getLogger(__name__)
ACTIVATION_SERVER_NAME = "monday-ui-rebuild"


class OrbWindow(QMainWindow):
    """Frameless transparent window hosting the Monday orb WebGL visualization."""

    def __init__(self, bridge: Bridge, request_quit) -> None:
        super().__init__()
        self._request_quit = request_quit
        self.setWindowTitle("MONDAY")
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, True)
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.WindowStaysOnTopHint |
            Qt.WindowType.Tool
        )
        self.resize(400, 400)

        self.view = QWebEngineView(self)
        self.view.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.view.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, True)
        self.view.page().setBackgroundColor(Qt.GlobalColor.transparent)
        self.setCentralWidget(self.view)

        # Allow local file access and JavaScript for file:// URLs
        settings = self.view.page().settings()
        settings.setAttribute(settings.WebAttribute.LocalContentCanAccessRemoteUrls, True)
        settings.setAttribute(settings.WebAttribute.LocalContentCanAccessFileUrls, True)
        settings.setAttribute(settings.WebAttribute.JavascriptEnabled, True)
        settings.setAttribute(settings.WebAttribute.WebGLEnabled, True)
        settings.setAttribute(settings.WebAttribute.Accelerated2dCanvasEnabled, True)

        self.channel = QWebChannel(self)
        self.channel.registerObject("bridge", bridge)
        self.view.page().setWebChannel(self.channel)

        orb_path = Path(__file__).with_name("monday_orb.html").resolve()
        self.view.setUrl(QUrl.fromLocalFile(str(orb_path)))

    def closeEvent(self, event) -> None:
        event.accept()
        self._request_quit()


class JarvisApp:
    """Own the Qt application, placeholder window, tray, and quit path."""

    def __init__(self, start_minimized: bool = False) -> None:
        self.app = QApplication.instance() or QApplication(sys.argv)
        self.app.setApplicationName("JARVIS")
        self.app.setOrganizationName("JARVIS")
        self.app.setQuitOnLastWindowClosed(False)

        self._app_icon = QIcon(self._make_tray_pixmap(256))
        self.app.setWindowIcon(self._app_icon)
        self.bridge = Bridge()
        self.wm = WindowManager(self.bridge)
        self.tray: QSystemTrayIcon | None = None
        self._tray_icon: QPixmap | None = None
        self.window = OrbWindow(self.bridge, self.bridge.quit_app)
        self.window.setWindowIcon(self._app_icon)
        self.wm.set_window(self.window)
        self.bridge.quitRequested.connect(
            self._quit, Qt.ConnectionType.QueuedConnection,
        )
        self._start_activation_server()
        tray_ready = self._setup_tray()
        if start_minimized and tray_ready:
            self.wm.hide_window()
        else:
            self.wm.show_window()
        self._idle_resource_timer = QTimer(self.app)
        self._idle_resource_timer.setInterval(5 * 60 * 1000)
        self._idle_resource_timer.timeout.connect(self._sample_idle_resources)
        self._idle_resource_timer.start()
    def _setup_tray(self) -> bool:
        if not QSystemTrayIcon.isSystemTrayAvailable():
            logger.info("System tray not available")
            return False

        self._tray_icon = self._make_tray_pixmap(22)
        self.tray = QSystemTrayIcon(QIcon(self._tray_icon), self.app)
        self.tray.setToolTip("MONDAY")
        menu = QMenu()

        show_action = QAction("Show MONDAY", menu)
        show_action.triggered.connect(self.wm.show_window)
        menu.addAction(show_action)

        hide_action = QAction("Hide MONDAY", menu)
        hide_action.triggered.connect(self.wm.hide_window)
        menu.addAction(hide_action)

        autostart_action = QAction("Launch at login", menu)
        autostart_action.setCheckable(True)
        autostart_action.setChecked(self._autostart_enabled())
        autostart_action.toggled.connect(self._set_autostart)
        menu.addAction(autostart_action)
        menu.addSeparator()

        quit_action = QAction("Quit", menu)
        quit_action.triggered.connect(self.bridge.quit_app)
        menu.addAction(quit_action)

        self.tray.setContextMenu(menu)
        self.tray.activated.connect(self._tray_activated)
        self.tray.show()
        return True

    def _autostart_enabled(self) -> bool:
        if sys.platform != "win32":
            return False
        import winreg

        try:
            with winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                r"Software\Microsoft\Windows\CurrentVersion\Run",
            ) as key:
                winreg.QueryValueEx(key, "MONDAY")
            return True
        except FileNotFoundError:
            return False

    def _set_autostart(self, enabled: bool) -> None:
        if sys.platform != "win32":
            return
        import winreg

        registry_path = r"Software\Microsoft\Windows\CurrentVersion\Run"
        with winreg.CreateKeyEx(
            winreg.HKEY_CURRENT_USER, registry_path, 0, winreg.KEY_SET_VALUE,
        ) as key:
            if enabled:
                pythonw = Path(sys.executable).with_name("pythonw.exe")
                if not pythonw.exists():
                    pythonw = Path(sys.executable)
                run_script = Path(__file__).resolve().parents[1] / "run.py"
                command = f'"{pythonw}" "{run_script}" --autostart'
                winreg.SetValueEx(key, "MONDAY", 0, winreg.REG_SZ, command)
            else:
                try:
                    winreg.DeleteValue(key, "MONDAY")
                except FileNotFoundError:
                    pass

    def _start_activation_server(self) -> None:
        self._activation_server = QLocalServer(self.app)
        QLocalServer.removeServer(ACTIVATION_SERVER_NAME)
        if not self._activation_server.listen(ACTIVATION_SERVER_NAME):
            logger.error("Cannot listen for second-instance activation: %s", self._activation_server.errorString())
            return
        self._activation_server.newConnection.connect(self._accept_activation)

    def _accept_activation(self) -> None:
        while self._activation_server.hasPendingConnections():
            client = self._activation_server.nextPendingConnection()
            if client.bytesAvailable():
                self._handle_activation(client)
            else:
                client.readyRead.connect(
                    lambda client=client: self._handle_activation(client),
                )
            client.disconnected.connect(client.deleteLater)

    def _handle_activation(self, client: QLocalSocket) -> None:
        if bytes(client.readAll()).strip().upper() == b"SHOW":
            self.bridge.show_window()
            client.write(b"OK")
            client.flush()

    def _sample_idle_resources(self) -> None:
        if self.bridge.coreState != "idle":
            return
        try:
            import psutil

            cpu = psutil.cpu_percent(interval=None)
            ram = psutil.virtual_memory().percent
        except Exception as exc:
            logger.debug("Idle resource sample unavailable: %s", exc)
            return
        logger.info("Idle resource sample (5m): CPU %.1f%% RAM %.1f%%", cpu, ram)
        if self.tray is not None:
            self.tray.setToolTip(f"MONDAY | idle CPU {cpu:.0f}% | RAM {ram:.0f}%")

    def _make_tray_pixmap(self, size: int) -> QPixmap:
        pixmap = QPixmap(size, size)
        pixmap.fill(Qt.GlobalColor.transparent)
        from PySide6.QtGui import QBrush, QColor

        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setBrush(QBrush(QColor("#ff7b00")))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawEllipse(1, 1, size - 2, size - 2)
        painter.end()
        return pixmap

    def _tray_activated(self, reason: QSystemTrayIcon.ActivationReason) -> None:
        if reason in (
            QSystemTrayIcon.ActivationReason.DoubleClick,
            QSystemTrayIcon.ActivationReason.Trigger,
        ):
            self.wm.show_window()

    def run(self) -> int:
        logger.info("JARVIS UI: Qt event loop starting")
        return self.app.exec()

    def _quit(self) -> None:
        logger.info("JARVIS UI: shutdown requested")
        self._activation_server.close()
        QLocalServer.removeServer(ACTIVATION_SERVER_NAME)
        self.app.quit()
