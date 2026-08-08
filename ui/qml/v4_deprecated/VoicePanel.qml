import QtQuick 2.15

/**
 * VoicePanel — waveform visualization with mic (blue, top) and assistant (orange, bottom) bars.
 */
Item {
    id: root

    property string coreMode: "idle"
    property real micEnergy: 0.0
    property real assistantEnergy: 0.0

    width: 400
    height: 60

    readonly property int barCount: 48
    readonly property real barWidth: 3
    readonly property real barSpacing: 5

    // Timer-driven animation tick for waveform (smoother at 60fps)
    property real animTick: 0
    Timer {
        interval: 50
        running: true
        repeat: true
        onTriggered: { root.animTick = Date.now() }
    }

    // ── Mic Waveform (top) ──
    Row {
        anchors.top: parent.top
        anchors.topMargin: 2
        anchors.horizontalCenter: parent.horizontalCenter
        spacing: barSpacing - barWidth
        Repeater {
            model: barCount
            Rectangle {
                width: barWidth
                height: Math.max(1, micBarHeight(index) * 0.5)
                radius: 1.5
                color: "#33aaff"
                opacity: 0.6 + 0.4 * root.micEnergy
                anchors.bottom: parent.bottom

                function micBarHeight(i) {
                    var t = (root.micEnergy * 20 + 2)
                    var phase = (i / barCount) * Math.PI * 2
                    var wave = Math.sin(phase + root.animTick * 0.005)
                    return Math.max(1, t * (0.5 + 0.5 * wave))
                }

                // Glow
                Rectangle {
                    width: parent.width + 4
                    height: parent.height + 4
                    radius: 3.5
                    color: "transparent"
                    border.width: 0.5
                    border.color: Qt.rgba(51/255, 170/255, 255/255, 0.15)
                    x: -2; y: -2
                    visible: parent.height > 5
                }
            }
        }
    }

    // ── Center Divider ──
    Rectangle {
        anchors.centerIn: parent
        width: parent.width * 0.8
        height: 1
        color: Qt.rgba(255/255, 140/255, 26/255, 0.15)
    }

    // ── Assistant Waveform (bottom) ──
    Row {
        anchors.bottom: parent.bottom
        anchors.bottomMargin: 2
        anchors.horizontalCenter: parent.horizontalCenter
        spacing: barSpacing - barWidth
        Repeater {
            model: barCount
            Rectangle {
                width: barWidth
                height: Math.max(1, assistantBarHeight(index) * 0.5)
                radius: 1.5
                color: "#ff8c1a"
                opacity: 0.6 + 0.4 * root.assistantEnergy
                anchors.top: parent.top

                function assistantBarHeight(i) {
                    var t = (root.assistantEnergy * 20 + 2)
                    var phase = (i / barCount) * Math.PI * 2
                    var wave = Math.sin(phase + root.animTick * 0.005 + Math.PI)
                    return Math.max(1, t * (0.5 + 0.5 * wave))
                }

                // Glow
                Rectangle {
                    width: parent.width + 4
                    height: parent.height + 4
                    radius: 3.5
                    color: "transparent"
                    border.width: 0.5
                    border.color: Qt.rgba(255/255, 140/255, 26/255, 0.15)
                    x: -2; y: -2
                    visible: parent.height > 5
                }
            }
        }
    }

    // ── Mode transition visibility ──
    opacity: 1
    Behavior on opacity { NumberAnimation { duration: 500; easing.type: Easing.OutCubic } }
}
