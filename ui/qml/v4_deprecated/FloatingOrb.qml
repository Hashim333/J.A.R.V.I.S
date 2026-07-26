import QtQuick 2.15
import QtQuick.Window 2.15
import QtQuick.Controls 2.15

/**
 * FloatingOrb — always-on-top floating orb with breathing animation, mode colors, and drag support.
 */
Window {
    id: root
    objectName: "orbWindow"
    title: "JARVIS Orb"
    width: 90
    height: 90
    visible: false
    flags: Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool
    color: "transparent"

    property string coreMode: "idle"
    property color coreColor: "#ff8c1a"
    property real glowIntensity: 0.45

    signal returnToFullscreen()
    signal quit()

    // ── Breathing animation ──
    property real breathe: 0
    NumberAnimation on breathe {
        loops: Animation.Infinite
        from: 0; to: 1
        duration: 1800
        easing.type: Easing.InOutSine
    }

    readonly property real breatheScale: 1.0 + 0.06 * (0.5 + 0.5 * Math.sin(breathe * Math.PI * 2))

    // ── Glow ring ──
    Rectangle {
        anchors.centerIn: parent
        width: 90 * breatheScale * 1.6
        height: 90 * breatheScale * 1.6
        radius: width / 2
        color: "transparent"
        gradient: RadialGradient {
            centerX: 0.5; centerY: 0.5; centerRadius: 0.5
            GradientStop { position: 0.0; color: Qt.rgba(coreColor.r, coreColor.g, coreColor.b, 0.3 * glowIntensity) }
            GradientStop { position: 0.5; color: Qt.rgba(coreColor.r, coreColor.g, coreColor.b, 0.08 * glowIntensity) }
            GradientStop { position: 1.0; color: "transparent" }
        }
        Behavior on color { ColorAnimation { duration: 500; easing.type: Easing.OutCubic } }
    }

    // ── Core orb ──
    Rectangle {
        anchors.centerIn: parent
        width: 90 * breatheScale
        height: 90 * breatheScale
        radius: width / 2
        gradient: RadialGradient {
            centerX: 0.5; centerY: 0.5; centerRadius: 0.5
            GradientStop { position: 0.0; color: Qt.lighter(coreColor, 1.6) }
            GradientStop { position: 0.4; color: coreColor }
            GradientStop { position: 0.8; color: Qt.darker(coreColor, 1.3) }
            GradientStop { position: 1.0; color: "#100500" }
        }
        Behavior on color { ColorAnimation { duration: 500; easing.type: Easing.OutCubic } }

        // Center hotspot
        Rectangle {
            anchors.centerIn: parent
            width: parent.width * 0.3
            height: parent.height * 0.3
            radius: width / 2
            gradient: RadialGradient {
                centerX: 0.5; centerY: 0.5; centerRadius: 0.5
                GradientStop { position: 0.0; color: "#ffffff" }
                GradientStop { position: 0.6; color: Qt.lighter(coreColor, 1.3) }
                GradientStop { position: 1.0; color: "transparent" }
            }
        }

        MouseArea {
            anchors.fill: parent
            drag.target: root
            drag.minimumX: 0
            drag.minimumY: 0
            onDoubleClicked: root.returnToFullscreen()
            acceptedButtons: Qt.LeftButton | Qt.RightButton
            onClicked: {
                if (mouse.button === Qt.RightButton) {
                    contextMenu.popup()
                }
            }
            cursorShape: Qt.PointingHandCursor
        }
    }

    // ── Context menu ──
    Menu {
        id: contextMenu
        MenuItem {
            text: "Return to Fullscreen"
            onTriggered: root.returnToFullscreen()
        }
        MenuItem {
            text: "Quit JARVIS"
            onTriggered: root.quit()
        }
    }

    // ── Mode reactivity ──
    Behavior on coreColor {
        ColorAnimation { duration: 500; easing.type: Easing.OutCubic }
    }
    Behavior on glowIntensity {
        NumberAnimation { duration: 500; easing.type: Easing.OutCubic }
    }
}