import QtQuick 2.15

Item {
    id: waveRoot

    property string currentMode: "idle"
    property real micEnergy: 0.0
    property real assistantEnergy: 0.0
    readonly property int barCount: 48

    property real _fade: 0.0

    onCurrentModeChanged: {
        _fade = (currentMode === "listening" || currentMode === "speaking") ? 1.0 : 0.0
    }
    Behavior on _fade { NumberAnimation { duration: 500; easing.type: Easing.OutCubic } }

    // ── Mic waveform (blue, top) ─────────────────────────────────────
    Row {
        id: micRow
        anchors.centerIn: parent
        anchors.verticalCenterOffset: -parent.height * 0.18
        spacing: parent.width / barCount * 0.35
        opacity: _fade * 0.9 * (currentMode === "listening" ? 1.0 : (currentMode === "speaking" ? 0.4 : 0.0))
        Behavior on opacity { NumberAnimation { duration: 300 } }

        Repeater {
            model: barCount
            Rectangle {
                property real _val: 0.0
                property real _target: 0.0
                width: Math.max(2.0, waveRoot.width / barCount * 0.5)
                height: Math.max(1, _val * waveRoot.height * 0.38)
                radius: width / 2
                color: Qt.rgba(0.2, 0.55, 0.95, 0.75 + 0.25 * _val)
                anchors.verticalCenter: parent.verticalCenter
                Behavior on height { SmoothedAnimation { velocity: 900; easing.type: Easing.OutQuad } }

                // Glow
                Rectangle {
                    anchors.fill: parent
                    radius: parent.radius
                    color: "transparent"
                    border.width: 1
                    border.color: Qt.rgba(0.2, 0.55, 0.95, 0.2 * _val)
                    opacity: _val
                }

                Timer {
                    interval: 32; running: true; repeat: true
                    onTriggered: {
                        var phase = (index / barCount) * Math.PI * 2
                        var t = Date.now() / 1000
                        var energy = waveRoot.micEnergy
                        _target = (Math.sin(t * 10 + phase * 2.5) * 0.35 + 0.5) * (0.15 + 0.85 * energy)
                        _val += (_target - _val) * 0.3
                    }
                }
            }
        }
    }

    // ── Assistant waveform (orange, bottom) ──────────────────────────
    Row {
        id: assistantRow
        anchors.centerIn: parent
        anchors.verticalCenterOffset: parent.height * 0.18
        spacing: parent.width / barCount * 0.3
        opacity: _fade * 0.9 * (currentMode === "speaking" ? 1.0 : (currentMode === "listening" ? 0.4 : 0.0))
        Behavior on opacity { NumberAnimation { duration: 300 } }

        Repeater {
            model: barCount
            Rectangle {
                property real _val: 0.0
                property real _target: 0.0
                width: Math.max(1.5, waveRoot.width / barCount * 0.45)
                height: Math.max(1, _val * waveRoot.height * 0.35)
                radius: width / 2
                color: Qt.rgba(1.0, 0.55, 0.1, 0.7 + 0.3 * _val)
                anchors.verticalCenter: parent.verticalCenter
                Behavior on height { SmoothedAnimation { velocity: 800; easing.type: Easing.OutQuad } }

                // Glow
                Rectangle {
                    anchors.fill: parent
                    radius: parent.radius
                    color: "transparent"
                    border.width: 1
                    border.color: Qt.rgba(1.0, 0.55, 0.1, 0.15 * _val)
                    opacity: _val
                }

                Timer {
                    interval: 32; running: true; repeat: true
                    onTriggered: {
                        var phase = (index / barCount) * Math.PI * 2
                        var t = Date.now() / 1000
                        var energy = waveRoot.assistantEnergy
                        _target = (Math.sin(t * 8 + phase * 1.8) * 0.35 + 0.5) * (0.15 + 0.85 * energy)
                        _val += (_target - _val) * 0.3
                    }
                }
            }
        }
    }

    // ── Center divider line (subtle) ─────────────────────────────────
    Rectangle {
        anchors.centerIn: parent
        width: parent.width * 0.85
        height: 0.5
        color: Qt.rgba(1, 0.55, 0.1, 0.08)
        opacity: _fade * 0.5
    }
}