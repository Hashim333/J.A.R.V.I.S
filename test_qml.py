import sys, os
from pathlib import Path
from PySide6.QtCore import QUrl, Qt
from PySide6.QtQml import QQmlApplicationEngine
from PySide6.QtWidgets import QApplication

sys.stdout = open("qml_test_out.txt", "w", encoding="utf-8")
sys.stderr = sys.stdout

app = QApplication(sys.argv)
engine = QQmlApplicationEngine()
engine.warnings.connect(lambda msg: print("QML WARN:", msg, flush=True))

qml_path = Path("ui/qml/v4/MainWindow.qml").resolve()
print("Loading:", str(qml_path), flush=True)

engine.rootContext().setContextProperty("bridge", None)
engine.rootContext().setContextProperty("uiConfig", None)
engine.addImportPath(str(Path("ui/qml/v4").resolve()))

engine.load(QUrl.fromLocalFile(str(qml_path)))

root_objects = engine.rootObjects()
print("Root objects:", len(root_objects), flush=True)
for o in root_objects:
    print("Root:", o, flush=True)

print("Done", flush=True)
sys.stdout.close()
