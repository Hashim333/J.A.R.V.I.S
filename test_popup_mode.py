import sys
import os
os.environ['QT_QPA_PLATFORM'] = 'windows:dpiawareness=2'
os.environ['QT_AUTO_SCREEN_SCALE_FACTOR'] = '1'
os.environ['QT_ENABLE_HIGHDPI_SCALING'] = '1'

sys.path.insert(0, '.')

from ui.bridge import Bridge
from ui.app import OrbWindow
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QTimer, QUrl, Qt
from PySide6.QtWebEngineCore import QWebEnginePage
from PySide6.QtWebEngineWidgets import QWebEngineView

# Monkey-patch QWebEnginePage to add debug logging
orig_console = QWebEnginePage.javaScriptConsoleMessage
def debug_console(self, level, message, lineNumber, sourceID):
    level_name = {0: 'Info', 1: 'Warning', 2: 'Error'}.get(level, 'Debug')
    print(f'JS [{level_name}] {sourceID}:{lineNumber}: {message}')
    return orig_console(self, level, message, lineNumber, sourceID)
QWebEnginePage.javaScriptConsoleMessage = debug_console

app = QApplication(sys.argv)
app.setQuitOnLastWindowClosed(False)

bridge = Bridge()
window = OrbWindow(bridge, app.quit)

window.show()

def check_window():
    print('Checking JS functions...')
    window.view.page().runJavaScript('typeof window.setWindowMode', lambda r: print(f'setWindowMode type: {r}'))
    window.view.page().runJavaScript('typeof window.setMondayState', lambda r: print(f'setMondayState type: {r}'))
    window.view.page().runJavaScript('document.body.className', lambda r: print(f'Body classes: {r}'))
    window.view.page().runJavaScript('window.setWindowMode("popup")', lambda r: print(f'setWindowMode result: {r}'))
    window.view.page().runJavaScript('document.body.className', lambda r: print(f'Body classes after: {r}'))
    window.grab().save('test_popup_full.png')
    print('Screenshot saved')
    app.quit()

QTimer.singleShot(5000, check_window)
app.exec()