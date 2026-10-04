"""Qt Widgets shell, tray, and application shutdown."""
from __future__ import annotations

import json
import logging
import os
import sys
from pathlib import Path

from PySide6.QtCore import QTimer, Qt, QUrl, QPoint, QRect, QScreen, QSize
from PySide6.QtGui import QAction, QIcon, QPainter, QPixmap, QColor, QCursor
from PySide6.QtNetwork import QLocalServer, QLocalSocket
from PySide6.QtWebChannel import QWebChannel
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWidgets import QApplication, QLabel, QMainWindow, QMenu, QSystemTrayIcon, QWidget

from ui.bridge import Bridge
from ui.window_manager import WindowManager

logger = logging.getLogger(__name__)
ACTIVATION_SERVER_NAME = "monday-ui-rebuild"

# Window mode constants
class WindowMode:
    POPUP = "popup"      # ~360x430, frameless, rounded, shadow
    EXPANDED = "expanded" # Large, full layout
    MINI = "mini"         # ~64px floating orb only

# Config file location
def get_config_path() -> Path:
    if sys.platform == "win32":
        base = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))
    else:
        base = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    return base / "JARVIS" / "window_config.json"


class OrbWindow(QMainWindow):
    """Frameless transparent window hosting the Monday orb Canvas 2D visualization.
    
    Three modes:
    - POPUP: ~360x430, frameless, rounded corners, dark #05070a, subtle shadow
    - EXPANDED: Large window, full layout
    - MINI: ~64px floating orb only (sphere + glow), always on top, draggable
    """

    # Mode-specific sizes (logical pixels, will be scaled by DPR)
    POPUP_SIZE = QSize(360, 430)
    MINI_SIZE = QSize(64, 64)
    EXPANDED_SIZE = QSize(600, 700)

    def __init__(self, bridge: Bridge, request_quit) -> None:
        super().__init__()
        self._request_quit = request_quit
        self._bridge = bridge
        self._mode = WindowMode.POPUP
        self._drag_pos: QPoint | None = None
        self._drag_start_pos: QPoint | None = None
        self._is_dragging = False
        self._click_pos: QPoint | None = None
        self._controls_widget: QWidget | None = None
        self._controls_visible = False

        self.setWindowTitle("MONDAY")
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, True)
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.WindowStaysOnTopHint |
            Qt.WindowType.Tool
        )

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
        settings.setAttribute(settings.WebAttribute.Accelerated2dCanvasEnabled, True)
        settings.setAttribute(settings.WebAttribute.WebGLEnabled, False)

        # Connect bridge state changes to orb JS
        bridge.stateChanged.connect(self._on_state_changed)

        orb_path = Path(__file__).with_name("monday_orb.html").resolve()
        logger.info("Loading orb from: %s", orb_path)
        self.view.setUrl(QUrl.fromLocalFile(str(orb_path)))

        # Debug: log load status and console messages
        self.view.loadFinished.connect(self._on_load_finished)
        self.view.page().javaScriptConsoleMessage = self._js_console_message

        # Load persisted config
        self._load_config()

        # Apply initial mode
        self._apply_mode(self._mode)

        # Create hover controls
        self._create_controls()

    def _on_state_changed(self, payload: dict) -> None:
        """Forward bridge state changes to orb JS."""
        # Use json.dumps for proper JS serialization (None -> null, strings escaped)
        js = f'window.setMondayState({json.dumps(payload.get("state", ""))}, {json.dumps(payload.get("label", ""))}, {json.dumps(payload.get("caption", ""))}, {payload.get("audio_level", 0.0)})'
        self.view.page().runJavaScript(js)

    def _on_load_finished(self, ok: bool) -> None:
        logger.info("Orb loadFinished: ok=%s", ok)
        if not ok:
            logger.error("Failed to load orb HTML")
        # Notify JS of current mode and radius factor
        self._sync_mode_to_js()
        # Grab screenshot for debugging
        self._grab_debug_screenshot()

    def _js_console_message(self, level, message, line, source_id):
        level_name = {0: "Info", 1: "Warning", 2: "Error"}.get(level, "Debug")
        logger.info("JS Console [%s] %s:%d - %s", level_name, source_id, line, message)

    def _grab_debug_screenshot(self) -> None:
        from PySide6.QtCore import QTimer
        QTimer.singleShot(500, self._do_grab)

    def _do_grab(self) -> None:
        pixmap = self.view.grab()
        if not pixmap.isNull():
            debug_dir = Path(__file__).parent / "dev_tests" / "screenshots"
            debug_dir.mkdir(parents=True, exist_ok=True)
            path = debug_dir / "orb_load_debug.png"
            pixmap.save(str(path))
            logger.info("Saved debug screenshot to %s (size: %dx%d)", path, pixmap.width(), pixmap.height())
        else:
            logger.warning("Grab returned null pixmap")

    # ========== Window Mode Management ==========

    def _apply_mode(self, mode: str) -> None:
        """Apply window mode: size, flags, radius factor, JS sync."""
        self._mode = mode
        screen = self.screen() or QApplication.primaryScreen()
        dpr = screen.devicePixelRatio() if screen else 1.0

        if mode == WindowMode.POPUP:
            self.resize(self.POPUP_SIZE)
            self._set_popup_flags()
            self._set_radius_factor(0.85)  # Balanced with negative space
            self._show_controls(True)
            self._set_rounded_corners(True)
        elif mode == WindowMode.EXPANDED:
            self.resize(self.EXPANDED_SIZE)
            self._set_expanded_flags()
            self._set_radius_factor(1.0)
            self._show_controls(True)
            self._set_rounded_corners(False)
        elif mode == WindowMode.MINI:
            self.resize(self.MINI_SIZE)
            self._set_mini_flags()
            self._set_radius_factor(1.5)  # Orb fills most of mini window
            self._show_controls(False)
            self._set_rounded_corners(True)
        else:
            logger.warning("Unknown window mode: %s", mode)
            return

        self._sync_mode_to_js()
        self._save_config()
        logger.info("Window mode changed to: %s", mode)

    def _set_popup_flags(self) -> None:
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.WindowStaysOnTopHint |
            Qt.WindowType.Tool
        )
        self.show()

    def _set_expanded_flags(self) -> None:
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.WindowStaysOnTopHint |
            Qt.WindowType.Tool
        )
        self.show()

    def _set_mini_flags(self) -> None:
        # Mini mode: always on top, no taskbar entry, click-through for orb area
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.WindowStaysOnTopHint |
            Qt.WindowType.Tool |
            Qt.WindowType.WindowTransparentForInput  # Allow click-through for orb
        )
        self.show()

    def _set_radius_factor(self, factor: float) -> None:
        """Send radius factor to JS."""
        js = f'window.setRadiusFactor({factor})'
        self.view.page().runJavaScript(js)

    def _sync_mode_to_js(self) -> None:
        """Sync current mode to JS for UI adaptation."""
        js = f'window.setWindowMode({json.dumps(self._mode)})'
        self.view.page().runJavaScript(js)

    def _show_controls(self, visible: bool) -> None:
        if self._controls_widget:
            self._controls_widget.setVisible(visible)
            self._controls_visible = visible

    def _set_rounded_corners(self, rounded: bool) -> None:
        """Tell JS to apply rounded corners."""
        js = f'window.setRoundedCorners({json.dumps(rounded)})'
        self.view.page().runJavaScript(js)

    # ========== Hover Controls ==========

    def _create_controls(self) -> None:
        """Create minimize/maximize/close controls as Qt overlay widgets."""
        self._controls_widget = QWidget(self)
        self._controls_widget.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self._controls_widget.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, True)
        self._controls_widget.setFixedSize(90, 28)
        self._controls_widget.setStyleSheet("""
            QWidget { background: transparent; }
            QPushButton {
                background: rgba(255,255,255,0.08);
                border: none;
                border-radius: 4px;
                color: #888;
                font-size: 12px;
                font-weight: bold;
            }
            QPushButton:hover {
                background: rgba(255,255,255,0.18);
                color: #fff;
            }
            QPushButton#closeBtn:hover {
                background: rgba(237, 80, 80, 0.9);
                color: #fff;
            }
        """)
        from PySide6.QtWidgets import QHBoxLayout, QPushButton
        layout = QHBoxLayout(self._controls_widget)
        layout.setContentsMargins(6, 4, 6, 4)
        layout.setSpacing(4)

        self._min_btn = QPushButton("−")
        self._min_btn.setFixedSize(20, 20)
        self._min_btn.setToolTip("Minimize to mini orb")
        self._min_btn.clicked.connect(self._on_minimize)

        self._max_btn = QPushButton("□")
        self._max_btn.setFixedSize(20, 20)
        self._max_btn.setToolTip("Expand")
        self._max_btn.clicked.connect(self._on_maximize_restore)

        self._close_btn = QPushButton("✕")
        self._close_btn.setFixedSize(20, 20)
        self._close_btn.setObjectName("closeBtn")
        self._close_btn.setToolTip("Hide to mini orb")
        self._close_btn.clicked.connect(self._on_close)

        layout.addWidget(self._min_btn)
        layout.addWidget(self._max_btn)
        layout.addWidget(self._close_btn)

        self._controls_widget.hide()
        self._position_controls()

    def _position_controls(self) -> None:
        if self._controls_widget:
            # Top-right corner with margin
            margin = 8
            x = self.width() - self._controls_widget.width() - margin
            y = margin
            self._controls_widget.move(x, y)

    def _on_minimize(self) -> None:
        self._apply_mode(WindowMode.MINI)

    def _on_maximize_restore(self) -> None:
        if self._mode == WindowMode.EXPANDED:
            self._apply_mode(WindowMode.POPUP)
        else:
            self._apply_mode(WindowMode.EXPANDED)

    def _on_close(self) -> None:
        # Close hides to MINI, doesn't quit
        self._apply_mode(WindowMode.MINI)

    # ========== Drag Handling ==========

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            # In MINI mode, allow dragging from anywhere
            # In POPUP/EXPANDED, only drag from empty area (not controls)
            if self._mode == WindowMode.MINI:
                self._drag_start_pos = event.globalPosition().toPoint()
                self._drag_pos = self.pos()
                self._is_dragging = True
                self._click_pos = event.position().toPoint()
            else:
                # Check if click is in controls area
                if self._controls_widget and self._controls_widget.geometry().contains(event.position().toPoint()):
                    return
                self._drag_start_pos = event.globalPosition().toPoint()
                self._drag_pos = self.pos()
                self._is_dragging = True
                self._click_pos = event.position().toPoint()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:
        if self._is_dragging and self._drag_start_pos is not None:
            delta = event.globalPosition().toPoint() - self._drag_start_pos
            new_pos = self._drag_pos + delta
            # Clamp to screen bounds
            new_pos = self._clamp_to_screen(new_pos)
            self.move(new_pos)
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            was_dragging = self._is_dragging
            self._is_dragging = False
            self._drag_start_pos = None
            self._drag_pos = None
            # In MINI mode, click (not drag) restores POPUP
            if self._mode == WindowMode.MINI and not was_dragging:
                self._apply_mode(WindowMode.POPUP)
        super().mouseReleaseEvent(event)

    def _clamp_to_screen(self, pos: QPoint) -> QPoint:
        """Clamp window position to visible screen area."""
        screen = QApplication.screenAt(pos) or QApplication.primaryScreen()
        if not screen:
            return pos
        geo = screen.availableGeometry()
        clamped_x = max(geo.left(), min(pos.x(), geo.right() - self.width()))
        clamped_y = max(geo.top(), min(pos.y(), geo.bottom() - self.height()))
        return QPoint(clamped_x, clamped_y)

    # ========== Enter/Leave Events for Hover Controls ==========

    def enterEvent(self, event) -> None:
        if self._mode != WindowMode.MINI:
            self._show_controls(True)
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:
        if self._mode != WindowMode.MINI:
            # Use a timer to allow moving into controls
            QTimer.singleShot(200, self._maybe_hide_controls)
        super().leaveEvent(event)

    def _maybe_hide_controls(self) -> None:
        if not self.underMouse() and self._controls_widget:
            self._show_controls(False)

    def resizeEvent(self, event) -> None:
        self._position_controls()
        super().resizeEvent(event)

    # ========== Config Persistence ==========

    def _load_config(self) -> None:
        config_path = get_config_path()
        if config_path.exists():
            try:
                with open(config_path, "r", encoding="utf-8") as f:
                    config = json.load(f)
                self._mode = config.get("mode", WindowMode.POPUP)
                pos = config.get("position")
                if pos:
                    self.move(pos[0], pos[1])
                # Validate position is on a valid screen
                self._validate_position()
                logger.info("Loaded window config: mode=%s, pos=(%d,%d)", 
                           self._mode, self.x(), self.y())
            except Exception as e:
                logger.warning("Failed to load window config: %s", e)
                self._mode = WindowMode.POPUP

    def _save_config(self) -> None:
        config_path = get_config_path()
        config_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            config = {
                "mode": self._mode,
                "position": [self.x(), self.y()],
            }
            with open(config_path, "w", encoding="utf-8") as f:
                json.dump(config, f)
        except Exception as e:
            logger.warning("Failed to save window config: %s", e)

    def _validate_position(self) -> None:
        """Ensure window is on a valid screen, move to primary if not."""
        screen = self.screen()
        if screen is None:
            # Window is on a non-existent monitor, move to primary
            primary = QApplication.primaryScreen()
            if primary:
                geo = primary.availableGeometry()
                self.move(geo.center() - self.rect().center())
                logger.info("Moved window to primary screen")

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
