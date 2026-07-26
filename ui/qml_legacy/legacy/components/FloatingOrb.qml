import QtQuick 2.15
import QtQuick.Window 2.15

Window {
    id: orbWindow
    objectName: "orbWindow"

    // ── Window flags for always-on-top, frameless floating orb ───────
    flags: Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool
    color: "transparent"
    width: 90
    height: 90

    // ── Bridge state ─────────────────────────────────────────────────
    property string currentMode: (typeof bridge !== "undefined" && bridge) ? bridge.coreState : "idle"
    Connections {
        target: typeof bridge !== "undefined" ? bridge : null
        function onCoreStateChanged(s) { if (orbWindow) orbWindow.currentMode = s }
    }

    // ── Drag support ─────────────────────────────────────────────────
    property real _dragX: 0
    property real _dragY: 0
    property bool _dragging: false
    property bool _hovered: false

    // ── Reactivate fullscreen on double-click ────────────────────────
    MouseArea {
        anchors.fill: parent
        hoverEnabled: true
        acceptedButtons: Qt.LeftButton | Qt.RightButton

        onEntered: _hovered = true
        onExited: _hovered = false

        onPressed: {
            if (mouse.button === Qt.LeftButton) {
                _dragX = mouse.x
                _dragY = mouse.y
                _dragging = true
            }
        }
        onPositionChanged: {
            if (_dragging && (mouse.buttons & Qt.LeftButton)) {
                orbWindow.x += mouse.x - _dragX
                orbWindow.y += mouse.y - _dragY
            }
        }
        onReleased: _dragging = false

        onDoubleClicked: {
            if (typeof bridge !== "undefined" && bridge) bridge.set_window_mode("fullscreen")
        }
    }

    // ── Dynamic color from state ─────────────────────────────────────
    property var _modeColors: { "idle": "#ff7b00", "listening": "#33aaff", "thinking": "#ffd700", "speaking": "#ff7b00", "error": "#ff3355", "offline": "#666666" }
    property color _orbColor: orbWindow._modeColors[orbWindow.currentMode] || "#ff7b00"
    Behavior on _orbColor { ColorAnimation { duration: 500 } }

    property color _orbColorLighter: Qt.lighter(orbWindow._orbColor, 1.5)
    property color _orbColorDarker: Qt.darker(orbWindow._orbColor, 1.3)

    // ── Outer glow ───────────────────────────────────────────────────
    Rectangle {
        anchors.centerIn: parent
        width: _hovered ? parent.width * 2.0 : parent.width * 1.6
        height: width; radius: width / 2
        color: "transparent"
        gradient: Gradient {
            GradientStop { position: 0.0; color: Qt.rgba(orbWindow._orbColor.r, orbWindow._orbColor.g, orbWindow._orbColor.b, 0.15) }
            GradientStop { position: 0.3; color: Qt.rgba(orbWindow._orbColor.r, orbWindow._orbColor.g, orbWindow._orbColor.b, 0.04) }
            GradientStop { position: 1.0; color: "transparent" }
        }
        opacity: _hovered ? 0.7 : 0.35
        Behavior on opacity { NumberAnimation { duration: 300 } }
        Behavior on width { NumberAnimation { duration: 300 } }
    }

    // ── Orb visual ───────────────────────────────────────────────────
    Rectangle {
        id: orbBall
        anchors.centerIn: parent
        width: _hovered ? parent.width * 0.85 : parent.width * 0.65
        height: width; radius: width / 2

        gradient: Gradient {
            GradientStop { position: 0.0; color: orbWindow._orbColorLighter }
            GradientStop { position: 0.45; color: orbWindow._orbColor }
            GradientStop { position: 1.0; color: orbWindow._orbColorDarker }
        }

        Behavior on width { NumberAnimation { duration: 200; easing.type: Easing.OutCubic } }

        // Glow halo
        Rectangle {
            anchors.centerIn: parent
            width: parent.width * 1.4; height: width; radius: width / 2
            color: "transparent"
            gradient: Gradient {
                GradientStop { position: 0.0; color: Qt.rgba(orbWindow._orbColor.r, orbWindow._orbColor.g, orbWindow._orbColor.b, 0.2) }
                GradientStop { position: 1.0; color: "transparent" }
            }
            opacity: _hovered ? 0.5 : 0.25
            Behavior on opacity { NumberAnimation { duration: 300 } }
        }

        // Core hotspot
        Rectangle {
            anchors.centerIn: parent
            width: parent.width * 0.35; height: width; radius: width / 2
            gradient: Gradient {
                GradientStop { position: 0.0; color: "#ffffff" }
                GradientStop { position: 0.4; color: orbWindow._orbColorLighter }
                GradientStop { position: 1.0; color: "transparent" }
            }
            opacity: 0.65
        }

        // Glare
        Rectangle {
            anchors.centerIn: parent
            width: parent.width * 0.6; height: width; radius: width / 2
            gradient: Gradient {
                GradientStop { position: 0.0; color: Qt.rgba(1, 1, 1, 0.25) }
                GradientStop { position: 0.3; color: Qt.rgba(orbWindow._orbColor.r, orbWindow._orbColor.g, orbWindow._orbColor.b, 0.08) }
                GradientStop { position: 1.0; color: "transparent" }
            }
            opacity: 0.4
        }

        SequentialAnimation on scale {
            loops: Animation.Infinite
            NumberAnimation { from: 1.0; to: 1.06; duration: 1800; easing.type: Easing.InOutSine }
            NumberAnimation { from: 1.06; to: 1.0; duration: 1800; easing.type: Easing.InOutSine }
        }
    }

    // ── Orbiting ring ────────────────────────────────────────────────
    Rectangle {
        anchors.centerIn: parent
        width: parent.width * 0.9
        height: width
        radius: width / 2
        color: "transparent"
        border.width: 0.5
        border.color: Qt.rgba(orbWindow._orbColor.r, orbWindow._orbColor.g, orbWindow._orbColor.b, 0.12)
        opacity: _hovered ? 0.6 : 0.3

        Rectangle {
            anchors.centerIn: parent
            width: parent.width * 0.7
            height: width
            radius: width / 2
            color: "transparent"
            border.width: 0.3
            border.color: Qt.rgba(orbWindow._orbColor.r, orbWindow._orbColor.g, orbWindow._orbColor.b, 0.08)
        }
    }

    // ── Right-click menu (simple QML) ───────────────────────────────
    Rectangle {
        id: orbMenu
        anchors { right: parent.right; top: parent.top; topMargin: 5 }
        width: 140; height: childrenRect.height
        color: "#1a1410"
        border.color: "#ff7b00"; border.width: 1
        radius: 8
        visible: false
        z: 100

        Column {
            width: parent.width; padding: 4
            Repeater {
                model: ["Full Screen", "Dock Left", "Dock Right", "Quit"]
                Rectangle {
                    width: parent.width - 8; height: 28; radius: 4; color: "transparent"
                    Text { text: modelData; color: "#cccccc"; font.pixelSize: 12; anchors.centerIn: parent }
                    MouseArea {
                        anchors.fill: parent; hoverEnabled: true
                        onEntered: parent.color = "#2a2018"
                        onExited: parent.color = "transparent"
                        onClicked: {
                            orbMenu.visible = false
                            if (modelData === "Full Screen" && typeof bridge !== "undefined" && bridge) { bridge.set_window_mode("fullscreen") }
                            else if (modelData === "Quit") { Qt.quit() }
                        }
                    }
                }
            }
        }
    }

    // ── Right-click to open menu ─────────────────────────────────────
    MouseArea {
        anchors.fill: parent
        acceptedButtons: Qt.RightButton
        onClicked: orbMenu.visible = !orbMenu.visible
    }
}