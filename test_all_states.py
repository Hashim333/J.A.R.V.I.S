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

screenshots_dir = Path('dev_tests/screenshots')
screenshots_dir.mkdir(parents=True, exist_ok=True)

states_to_test = [
    ('PASSIVE', 'Passive', 'Ready when you are.', 0.0),
    ('WAKE', 'Wake Detected', 'Wake word detected', 0.0),
    ('LISTENING', 'Listening', 'Listening...', 0.5),
    ('UNDERSTANDING', 'Understanding', 'Understanding...', 0.0),
    ('THINKING', 'Thinking', 'Thinking...', 0.0),
    ('WORKING', 'Working', 'Working...', 0.0),
    ('SPEAKING', 'Speaking', 'Speaking...', 0.8),
    ('DONE', 'Done', 'Done', 0.0),
    ('ERROR', 'Error', 'Something went wrong', 0.0),
]

def capture_state(index):
    if index >= len(states_to_test):
        print('All states tested')
        app.quit()
        return
    
    state, label, caption, audio = states_to_test[index]
    print(f'Testing state: {state}')
    bridge.emit_state(state, label, caption, audio)
    
    def save_screenshot():
        pixmap = view.grab()
        if not pixmap.isNull():
            filename = screenshots_dir / f'orb_{state.lower()}.png'
            pixmap.save(str(filename))
            print(f'Saved {filename} ({pixmap.width()}x{pixmap.height()})')
        else:
            print('Grab returned null pixmap')
        
        QTimer.singleShot(800, lambda: capture_state(index + 1))
    
    QTimer.singleShot(600, save_screenshot)

QTimer.singleShot(1500, lambda: capture_state(0))
app.exec()