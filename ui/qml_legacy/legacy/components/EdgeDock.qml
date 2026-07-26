import QtQuick 2.15
import QtQuick.Window 2.15

Window {
    id: dockWindow
    objectName: "dockWindow"

    flags: Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool
    color: "transparent"

    property string dockEdge: "left"
    property bool expanded: false

    function _reposition() {
        var screenW = Screen.width
        var screenH = Screen.height
        if (screenW <= 0 || screenH <= 0) return
        switch (dockEdge) {
            case "left":
                x = 0; y = 0
                width = expanded ? 260 : 48
                height = screenH
                break
            case "right":
                x = screenW - (expanded ? 260 : 48); y = 0
                width = expanded ? 260 : 48
                height = screenH
                break
            case "top":
                x = 0; y = 0
                width = screenW
                height = expanded ? 200 : 48
                break
            case "bottom":
                x = 0; y = screenH - (expanded ? 200 : 48)
                width = screenW
                height = expanded ? 200 : 48
                break
        }
    }

    onDockEdgeChanged: _reposition()
    onExpandedChanged: _reposition()

    Component.onCompleted: _reposition()

    // ── Hover to expand ──────────────────────────────────────────────
    MouseArea {
        anchors.fill: parent
        hoverEnabled: true
        onEntered: expanded = true
        onExited: expanded = false
    }

    // ── Content panel ────────────────────────────────────────────────
    Rectangle {
        anchors.fill: parent
        color: Qt.rgba(10, 8, 6, 0.85)
        radius: dockEdge === "left" || dockEdge === "right" ? 0 : 0

        // Border accent
        Rectangle {
            anchors {
                left: dockEdge === "left" ? parent.right : undefined
                right: dockEdge === "right" ? parent.left : undefined
                top: dockEdge === "top" ? parent.bottom : undefined
                bottom: dockEdge === "bottom" ? parent.top : undefined
                verticalCenter: (dockEdge === "left" || dockEdge === "right") ? parent.verticalCenter : undefined
                horizontalCenter: (dockEdge === "top" || dockEdge === "bottom") ? parent.horizontalCenter : undefined
            }
            width: dockEdge === "left" || dockEdge === "right" ? 1 : parent.width
            height: dockEdge === "top" || dockEdge === "bottom" ? 1 : parent.height
            color: Qt.rgba(1, 0.48, 0, 0.15)
            visible: !dockWindow.expanded
        }

        // Collapsed label
        Text {
            anchors.centerIn: parent
            text: "|||"
            color: "#555"
            font { pixelSize: 12; letterSpacing: 2 }
            visible: !dockWindow.expanded
        }

        // Expanded content
        Text {
            anchors { top: parent.top; topMargin: 20; left: parent.left; leftMargin: 20 }
            text: "JARVIS Dock"
            color: "#ff7b00"
            font { pixelSize: 16; bold: true; letterSpacing: 2 }
            visible: dockWindow.expanded
        }
    }
}
