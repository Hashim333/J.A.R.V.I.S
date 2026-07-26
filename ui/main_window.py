"""
ui/main_window.py

Creates the QApplication, QQmlApplicationEngine, and displays the
full-screen JARVIS UI window.
"""

from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtCore import QUrl, Qt
from PySide6.QtGui import QGuiApplication, QSurfaceFormat
from PySide6.QtQml import QQmlApplicationEngine


def create_application() -> QGuiApplication:
    """Build and configure the QGuiApplication."""
    app = QGuiApplication(sys.argv)
    app.setApplicationName("JARVIS")
    app.setOrganizationName("JARVIS")

    fmt = QSurfaceFormat()
    fmt.setSamples(4)
    fmt.setSwapInterval(1)
    QSurfaceFormat.setDefaultFormat(fmt)

    return app


def launch(bridge: object) -> int:
    """Create the QML engine, load main.qml, and enter the event loop.

    Returns the application exit code.
    """
    app = create_application()

    engine = QQmlApplicationEngine()
    engine.rootContext().setContextProperty("bridge", bridge)

    qml_path = Path(__file__).parent / "qml" / "main.qml"
    engine.load(QUrl.fromLocalFile(str(qml_path)))

    if not engine.rootObjects():
        return -1

    return app.exec()
