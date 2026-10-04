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
    @Slot(str, str, str, float)
    def emit_state(self, state, label, caption, audio_level):
        print('Bridge.emit_state:', state)
        self.stateChanged.emit({'state': state, 'label': label, 'caption': caption, 'audio_level': audio_level})

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

def test_direct_call():
    print('Testing direct JS call...')
    view.page().runJavaScript('console.log("Direct JS call works"); window.setMondayState("LISTENING", "Listening", "Listening...")', lambda result: print('JS result:', result))

def test_bridge_signal():
    print('Testing bridge signal...')
    bridge.emit_state('WORKING', 'Working', 'Working...', 0.0)

def save_and_quit():
    view.grab().save('test_direct.png')
    print('Screenshot saved')
    app.quit()

QTimer.singleShot(2000, test_direct_call)
QTimer.singleShot(3000, test_bridge_signal)
QTimer.singleShot(4000, save_and_quit)
app.exec()