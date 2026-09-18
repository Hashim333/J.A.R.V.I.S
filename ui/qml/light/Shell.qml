import QtQuick 2.15
import QtQuick.Window 2.15

/**
 * Shell — lightweight JARVIS presentation shell.
 *
 * Presentation only. The backend owns all state; this file only renders
 * bridge.coreState / bridge subtitle text. No microphone, no VAD/STT/TTS,
 * no system polling, no particles, no canvases.
 *
 * Cost: one circle + two text items + one slow opacity/scale animation.
 * All updates are event-driven (bridge signals); nothing polls.
 */
Window {
    id: root
    objectName: "jarvisShellWindow"
    title: "JARVIS"
    width: 640
    height: 420
    minimumWidth: 480
    minimumHeight: 320
    visible: true
    color: "#000000"

    flags: Qt.FramelessWindowHint | Qt.WindowMinimizeButtonHint | Qt.WindowMaximizeButtonHint

    property string coreMode: "idle"
    property string subtitleText: ""

    function modeColor(mode) {
        if (mode === "listening") return "#33aaff"
        if (mode === "thinking") return "#ffd700"
        if (mode === "speaking") return "#ff8c1a"
        if (mode === "error") return "#ff3355"
        if (mode === "offline") return "#444444"
        return "#ff8c1a"
    }

    // ── Drag bar ──
    MouseArea {
        anchors.top: parent.top
        anchors.left: parent.left
        anchors.right: parent.right
        height: 36
        onPressed: { root.startSystemMove() }
    }

    // ── Window controls ──
    Row {
        anchors.top: parent.top
        anchors.right: parent.right
        anchors.margins: 10
        spacing: 8
        Text {
            text: "—"
            color: "#888888"
            font.pixelSize: 16
            MouseArea {
                anchors.fill: parent
                cursorShape: Qt.PointingHandCursor
                onClicked: {
                    if (typeof bridge !== "undefined" && bridge && bridge.minimize_window)
                        bridge.minimize_window()
                    else
                        root.showMinimized()
                }
            }
        }
        Text {
            text: "✕"
            color: "#888888"
            font.pixelSize: 14
            MouseArea {
                anchors.fill: parent
                cursorShape: Qt.PointingHandCursor
                onClicked: {
                    if (typeof bridge !== "undefined" && bridge && bridge.quit_app)
                        bridge.quit_app()
                    else
                        Qt.quit()
                }
            }
        }
    }

    // ── Center column ──
    Column {
        anchors.centerIn: parent
        spacing: 10

        Text {
            anchors.horizontalCenter: parent.horizontalCenter
            text: "JARVIS"
            color: "#ffffff"
            font.pixelSize: 30
            font.letterSpacing: 10
            font.weight: Font.Light
        }

        // Orb: single circle, slow glow pulse. One animation only.
        Rectangle {
            id: orb
            anchors.horizontalCenter: parent.horizontalCenter
            width: 110
            height: 110
            radius: 55
            color: "transparent"
            border.color: root.modeColor(root.coreMode)
            border.width: 2

            Rectangle {
                anchors.centerIn: parent
                width: 72
                height: 72
                radius: 36
                color: root.modeColor(root.coreMode)
                opacity: 0.85

                SequentialAnimation on opacity {
                    loops: Animation.Infinite
                    NumberAnimation { from: 0.85; to: 0.45; duration: 1600; easing.type: Easing.InOutSine }
                    NumberAnimation { from: 0.45; to: 0.85; duration: 1600; easing.type: Easing.InOutSine }
                }
            }
        }

        Text {
            anchors.horizontalCenter: parent.horizontalCenter
            text: root.coreMode.toUpperCase()
            color: root.modeColor(root.coreMode)
            font.pixelSize: 16
            font.letterSpacing: 6
        }

        Text {
            anchors.horizontalCenter: parent.horizontalCenter
            text: root.subtitleText
            color: "#999999"
            font.pixelSize: 13
            visible: root.subtitleText !== ""
            width: Math.min(implicitWidth, root.width - 80)
            wrapMode: Text.WordWrap
            horizontalAlignment: Text.AlignHCenter
        }
    }

    // ── Backend bindings (read-only) ──
    Connections {
        target: bridge
        ignoreUnknownSignals: true
        function onCoreStateChanged(state) { root.coreMode = state }
        function onSubtitleChanged(text) { root.subtitleText = text }
    }

    Component.onCompleted: {
        try {
            root.coreMode = bridge.coreState || "idle"
        } catch (e) {}
    }

    Shortcut { sequence: "Escape"; onActivated: root.showMinimized() }
}
