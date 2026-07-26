import QtQuick 2.15
import QtQuick.Window 2.15
import QtQuick.Effects

Window {
    id: orbWindow
    objectName: "orbWindow"
    width: 140
    height: 140
    flags: Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool
    color: "transparent"

    Theme { id: theme }

    property string mode: bridge ? bridge.coreState : "idle"
    
    property color accentColor: theme.accentForMode(mode)
    Behavior on accentColor { ColorAnimation { duration: 300 } }

    Item {
        id: orbVisuals
        anchors.fill: parent

        Rectangle {
            anchors.fill: parent
            radius: width / 2
            color: theme.panelDark
            border.color: Qt.rgba(accentColor.r, accentColor.g, accentColor.b, 0.3)
            border.width: 2
        }

        AiCore {
            id: miniCore
            anchors.centerIn: parent
            width: parent.width * 0.9
            height: parent.height * 0.9
            mode: orbWindow.mode
        }
    }

    MultiEffect {
        anchors.fill: orbVisuals
        source: orbVisuals
        blurEnabled: true
        blur: 1.0
        blurMax: 16
        colorization: 1.0
        colorizationColor: accentColor
    }

    MouseArea {
        anchors.fill: parent
        onPressed: {
            orbWindow.startSystemMove()
        }
        onDoubleClicked: {
            if(bridge) bridge.set_window_mode("fullscreen")
        }
    }
}
