import sys
import os
os.environ['QT_QPA_PLATFORM'] = 'windows:dpiawareness=2'
os.environ['QT_AUTO_SCREEN_SCALE_FACTOR'] = '1'
os.environ['QT_ENABLE_HIGHDPI_SCALING'] = '1'

from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QTimer, QUrl, Qt, QObject, Signal, Slot
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWebEngineCore import QWebEnginePage, QWebEngineSettings
from pathlib import Path

class DebugPage(QWebEnginePage):
    def javaScriptConsoleMessage(self, level, message, lineNumber, sourceID):
        level_name = {0: 'Info', 1: 'Warning', 2: 'Error'}.get(level, 'Debug')
        print(f'JS Console [{level_name}] {sourceID}:{lineNumber}: {message}')
        super().javaScriptConsoleMessage(level, message, lineNumber, sourceID)

# Bridge class matching the real one
class Bridge(QObject):
    stateChanged = Signal(dict)
    
    @Slot(str, str, str, float)
    def emit_state(self, state, label, caption, audio_level):
        print(f'Python: emit_state({state})')
        self.stateChanged.emit({'state': state, 'label': label, 'caption': caption, 'audio_level': audio_level})

app = QApplication(sys.argv)
app.setQuitOnLastWindowClosed(False)

bridge = Bridge()

view = QWebEngineView()
view.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
view.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, True)

page = DebugPage(view)
page.setBackgroundColor(Qt.GlobalColor.transparent)
view.setPage(page)

settings = page.settings()
settings.setAttribute(QWebEngineSettings.WebAttribute.LocalContentCanAccessRemoteUrls, True)
settings.setAttribute(QWebEngineSettings.WebAttribute.LocalContentCanAccessFileUrls, True)
settings.setAttribute(QWebEngineSettings.WebAttribute.JavascriptEnabled, True)
settings.setAttribute(QWebEngineSettings.WebAttribute.Accelerated2dCanvasEnabled, True)
settings.setAttribute(QWebEngineSettings.WebAttribute.WebGLEnabled, False)

# Connect bridge state changes to orb JS (like OrbWindow does)
def on_state_changed(payload: dict) -> None:
    state = payload.get("state", "")
    label = payload.get("label", "")
    caption = payload.get("caption", "")
    audio_level = payload.get("audio_level", 0.0)
    js = f'window.setMondayState("{state}", "{label}", "{caption}", {audio_level})'
    view.page().runJavaScript(js)

bridge.stateChanged.connect(on_state_changed)

orb_path = Path('ui/monday_orb.html').resolve()
print('Loading:', orb_path)

page.loadFinished.connect(lambda ok: print(f'loadFinished: {ok}'))
view.setUrl(QUrl.fromLocalFile(str(orb_path)))
view.resize(480, 480)
view.show()

def test_bridge():
    print('Python: Emitting WORKING state via bridge...')
    bridge.emit_state('WORKING', 'Working', 'Working...', 0.0)

def test_bridge2():
    print('Python: Emitting LISTENING state via bridge...')
    bridge.emit_state('LISTENING', 'Listening', 'Listening...', 0.5)

def test_bridge3():
    print('Python: Emitting SPEAKING state via bridge...')
    bridge.emit_state('SPEAKING', 'Speaking', 'Speaking...', 0.8)

def test_bridge4():
    print('Python: Emitting PASSIVE state via bridge...')
    bridge.emit_state('PASSIVE', 'Passive', 'Ready when you are.', 0.0)

def save_and_quit():
    view.grab().save('test_direct_signal.png')
    print('Screenshot saved')
    app.quit()

QTimer.singleShot(2000, test_bridge)
QTimer.singleShot(3000, test_bridge2)
QTimer.singleShot(4000, test_bridge3)
QTimer.singleShot(5000, test_bridge4)
QTimer.singleShot(6000, save_and_quit)
app.exec()