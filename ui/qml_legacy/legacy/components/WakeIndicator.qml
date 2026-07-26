import QtQuick 2.15

Item {
    id: wakeRoot

    height: textItem.height + 24
    width: textItem.width + 48

    // ── Background pill (glass) ──────────────────────────────────────
    Rectangle {
        anchors.fill: parent
        radius: height / 2
        color: Qt.rgba(1, 0.48, 0, 0.08)
        border.width: 1
        border.color: Qt.rgba(1, 0.48, 0, 0.2)

        SequentialAnimation on opacity {
            running: wakeRoot.visible
            loops: Animation.Infinite
            NumberAnimation { from: 0.8; to: 1.0; duration: 1200; easing.type: Easing.InOutSine }
            NumberAnimation { from: 1.0; to: 0.8; duration: 1200; easing.type: Easing.InOutSine }
        }
    }

    // ── Text ─────────────────────────────────────────────────────────
    Text {
        id: textItem
        anchors.centerIn: parent
        text: "Listening..."
        color: "#ff7b00"
        font { family: "Segoe UI"; pixelSize: 14; weight: Font.Light; letterSpacing: 2 }

        SequentialAnimation on opacity {
            running: wakeRoot.visible
            loops: Animation.Infinite
            NumberAnimation { from: 0.7; to: 1.0; duration: 1200; easing.type: Easing.InOutSine }
            NumberAnimation { from: 1.0; to: 0.7; duration: 1200; easing.type: Easing.InOutSine }
        }
    }

    // ── Animated dots ────────────────────────────────────────────────
    Row {
        anchors { left: textItem.right; leftMargin: 4; bottom: textItem.baseline; bottomMargin: -2 }
        spacing: 3

        Repeater {
            model: 3
            Rectangle {
                width: 3; height: 3; radius: 1.5
                color: "#ff7b00"

                SequentialAnimation on opacity {
                    running: wakeRoot.visible
                    loops: Animation.Infinite
                    PauseAnimation { duration: index * 300 }
                    NumberAnimation { from: 0.0; to: 1.0; duration: 400; easing.type: Easing.InOutSine }
                    NumberAnimation { from: 1.0; to: 0.0; duration: 400; easing.type: Easing.InOutSine }
                }
            }
        }
    }

    // ── Fade in/out on visibility ───────────────────────────────────
    opacity: visible ? 1.0 : 0.0
    Behavior on opacity { NumberAnimation { duration: 300 } }
}
