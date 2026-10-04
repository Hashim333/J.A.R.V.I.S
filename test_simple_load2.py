import sys
import os
os.environ['QT_QPA_PLATFORM'] = 'windows:dpiawareness=2'
os.environ['QT_AUTO_SCREEN_SCALE_FACTOR'] = '1'
os.environ['QT_ENABLE_HIGHDPI_SCALING'] = '1'

from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QTimer, Qt, QUrl
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWebEngineCore import QWebEnginePage, QWebEngineSettings
from pathlib import Path

class DebugPage(QWebEnginePage):
    def javaScriptConsoleMessage(self, level, message, lineNumber, sourceID):
        level_name = {0: 'Info', 1: 'Warning', 2: 'Error'}.get(level, 'Debug')
        print(f'JS [{level_name}] {sourceID}:{lineNumber}: {message}')
        super().javaScriptConsoleMessage(level, message, lineNumber, sourceID)

app = QApplication(sys.argv)
app.setQuitOnLastWindowClosed(False)

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

orb_path = Path('ui/monday_orb.html').resolve()
print('Path exists:', orb_path.exists())
print('Path:', orb_path)

# Try with file:// URL
file_url = QUrl.fromLocalFile(str(orb_path))
print('File URL:', file_url.toString())

view.setUrl(file_url)
view.resize(360, 430)
view.show()

# Check load progress
view.loadProgress.connect(lambda p: print(f'Load progress: {p}%'))
view.loadFinished.connect(lambda ok: print(f'Load finished: {ok}'))

def check():
    print('Checking...')
    view.page().runJavaScript('document.body.innerHTML', lambda r: print('Body HTML:', r[:500] if r else 'empty'))
    view.page().runJavaScript('typeof window.setWindowMode', lambda r: print('setWindowMode:', r))
    view.grab().save('test_simple.png')
    print('Screenshot saved')
    app.quit()

import time
time.sleep(1)
# Check if load finished
QTimer.singleShot(5000, check)
app.exec()