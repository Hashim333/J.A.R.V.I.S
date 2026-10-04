import sys
import os
os.environ['QT_QPA_PLATFORM'] = 'windows:dpiawareness=2'
os.environ['QT_AUTO_SCREEN_SCALE_FACTOR'] = '1'
os.environ['QT_ENABLE_HIGHDPI_SCALING'] = '1'

from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QTimer, QUrl, Qt, QObject, Signal, Slot
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWebChannel import QWebChannel
from PySide6.QtWebEngineCore import QWebEngineSettings
from pathlib import Path

app = QApplication(sys.argv)
app.setQuitOnLastWindowClosed(False)

view = QWebEngineView()
view.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
view.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, True)
view.page().setBackgroundColor(Qt.GlobalColor.transparent)

settings = view.page().settings()
settings.setAttribute(QWebEngineSettings.WebAttribute.LocalContentCanAccessRemoteUrls, True)
settings.setAttribute(QWebEngineSettings.WebAttribute.LocalContentCanAccessFileUrls, True)
settings.setAttribute(QWebEngineSettings.WebAttribute.JavascriptEnabled, True)
settings.setAttribute(QWebEngineSettings.WebAttribute.Accelerated2dCanvasEnabled, True)
settings.setAttribute(QWebEngineSettings.WebAttribute.WebGLEnabled, False)

class Bridge(QObject):
    stateChanged = Signal(dict)

bridge = Bridge()
channel = QWebChannel()
channel.registerObject('bridge', bridge)
view.page().setWebChannel(channel)

orb_path = Path('ui/monday_orb.html').resolve()
print('Loading:', orb_path)

def js_console(level, msg, line, src):
    print(f'JS[{level}] {src}:{line} {msg}')
view.page().javaScriptConsoleMessage = js_console

view.loadFinished.connect(lambda ok: print(f'loadFinished: {ok}'))
view.setUrl(QUrl.fromLocalFile(str(orb_path)))
view.resize(480, 480)
view.show()

def check_qt():
    print('Checking qt object...')
    view.page().runJavaScript('console.log("typeof QWebChannel:", typeof QWebChannel); console.log("typeof qt:", typeof qt); console.log("qt.webChannelTransport:", qt && qt.webChannelTransport)', lambda r: print('Result:', r))

QTimer.singleShot(2000, check_qt)
QTimer.singleShot(4000, lambda: app.quit())
app.exec()