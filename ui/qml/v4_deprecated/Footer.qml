import QtQuick 2.15

/**
 * Footer — bottom section with preview cards and mini voice waveform.
 */
Rectangle {
    id: root

    property real micEnergy: 0.0
    property real animTick: 0
    Timer {
        interval: 32
        running: true
        repeat: true
        onTriggered: { root.animTick = Date.now() }
    }

    width: parent.width
    height: 64
    color: Qt.rgba(8/255, 6/255, 5/255, 0.90)
    z: 4

    // Top border
    Rectangle {
        anchors.top: parent.top
        width: parent.width
        height: 1
        color: Qt.rgba(255/255, 140/255, 26/255, 0.06)
    }

    // Preview cards
    BottomCards {
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.rightMargin: 180
        anchors.verticalCenter: parent.verticalCenter
        height: parent.height
    }

    // Voice mini section
    Item {
        anchors.right: parent.right
        anchors.rightMargin: 20
        anchors.verticalCenter: parent.verticalCenter
        width: 160
        height: parent.height

        Text {
            anchors.top: parent.top
            anchors.topMargin: 8
            anchors.right: parent.right
            text: "VOICE"
            font.family: "Segoe UI"
            font.pixelSize: 6
            font.letterSpacing: 2
            color: "#776655"
        }

        // Mini waveform
        Row {
            anchors.bottom: parent.bottom
            anchors.bottomMargin: 12
            anchors.right: parent.right
            spacing: 2
            Repeater {
                model: 16
                Rectangle {
                    width: 3
                    height: Math.max(1, (root.micEnergy * 15 + 2) * (0.5 + 0.5 * Math.sin((index / 16) * Math.PI * 2 + root.animTick * 0.005)))
                    radius: 1.5
                    color: "#ff8c1a"
                    opacity: 0.4 + 0.3 * root.micEnergy
                    anchors.bottom: parent.bottom
                }
            }
        }
    }
}