import QtQuick 2.15
import QtQuick.Window 2.15

Window {
    id: root
    objectName: "fullscreenWindow"
    title: "JARVIS Desktop"
    width: 1920
    height: 1080
    visible: true
    color: "#000000"
    minimumWidth: 1280
    minimumHeight: 720

    flags: Qt.FramelessWindowHint | Qt.WindowMinimizeButtonHint | Qt.WindowMaximizeButtonHint

    property bool isWindowMaximized: false
    property bool isWindowMinimized: false

    Dashboard {
        id: dashboard
        anchors.fill: parent
    }

    function doMinimize() {
        if (typeof bridge !== 'undefined' && bridge && bridge.minimize_window) {
            bridge.minimize_window()
        } else {
            root.showMinimized()
        }
    }
    function doMaximize() {
        if (root.isWindowMaximized) { root.showNormal() }
        else { root.showMaximized() }
    }
    function doClose() {
        if (typeof bridge !== 'undefined' && bridge && bridge.quit_app) {
            bridge.quit_app()
        } else {
            Qt.quit()
        }
    }
    function doStartMove() {
        if (!root.isWindowMaximized) root.startSystemMove()
    }
    function doToggleMax() {
        if (root.isWindowMaximized) { root.showNormal() }
        else { root.showMaximized() }
    }

    onWindowStateChanged: {
        root.isWindowMaximized = (root.windowState & Qt.WindowMaximized)
        root.isWindowMinimized = (root.windowState & Qt.WindowMinimized)
    }

    // ── Resize edges ──
    MouseArea {
        anchors.left: parent.left; anchors.top: parent.top; anchors.bottom: parent.bottom
        width: 6; cursorShape: Qt.SizeHorCursor
        onPressed: {
            if (!root.isWindowMaximized) root.startSystemResize(Qt.LeftEdge)
        }
    }
    MouseArea {
        anchors.right: parent.right; anchors.top: parent.top; anchors.bottom: parent.bottom
        width: 6; cursorShape: Qt.SizeHorCursor
        onPressed: {
            if (!root.isWindowMaximized) root.startSystemResize(Qt.RightEdge)
        }
    }
    MouseArea {
        anchors.bottom: parent.bottom; anchors.left: parent.left; anchors.right: parent.right
        height: 6; cursorShape: Qt.SizeVerCursor
        onPressed: {
            if (!root.isWindowMaximized) root.startSystemResize(Qt.BottomEdge)
        }
    }
    MouseArea {
        anchors.top: parent.top; anchors.left: parent.left; anchors.right: parent.right
        height: 6; cursorShape: Qt.SizeVerCursor
        onPressed: {
            if (!root.isWindowMaximized) root.startSystemResize(Qt.TopEdge)
        }
    }
    MouseArea { anchors.top: parent.top; anchors.left: parent.left
        width: 12; height: 12; cursorShape: Qt.SizeFDiagCursor
        onPressed: {
            if (!root.isWindowMaximized) root.startSystemResize(Qt.TopEdge | Qt.LeftEdge)
        }
    }
    MouseArea { anchors.top: parent.top; anchors.right: parent.right
        width: 12; height: 12; cursorShape: Qt.SizeBDiagCursor
        onPressed: {
            if (!root.isWindowMaximized) root.startSystemResize(Qt.TopEdge | Qt.RightEdge)
        }
    }
    MouseArea { anchors.bottom: parent.bottom; anchors.left: parent.left
        width: 12; height: 12; cursorShape: Qt.SizeBDiagCursor
        onPressed: {
            if (!root.isWindowMaximized) root.startSystemResize(Qt.BottomEdge | Qt.LeftEdge)
        }
    }
    MouseArea { anchors.bottom: parent.bottom; anchors.right: parent.right
        width: 12; height: 12; cursorShape: Qt.SizeFDiagCursor
        onPressed: {
            if (!root.isWindowMaximized) root.startSystemResize(Qt.BottomEdge | Qt.RightEdge)
        }
    }

    Shortcut { sequence: "Escape"; onActivated: root.doMinimize() }
    Shortcut { sequence: "F11"; onActivated: root.doToggleMax() }
}