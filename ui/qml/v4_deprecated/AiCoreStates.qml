import QtQuick 2.15

Column {
    id: root
    spacing: 10

    property string currentMode: "idle"
    property real scale: 1.0

    readonly property var modes: [
        { id: "idle", label: "IDLE", desc: "Calm, breathing glow", color: "#ff8c1a", line: 0 },
        { id: "listening", label: "LISTENING", desc: "Expands, blue particles", color: "#33aaff", line: 1 },
        { id: "thinking", label: "THINKING", desc: "Faster rotation, data pulses", color: "#ff8c1a", line: 2 },
        { id: "speaking", label: "SPEAKING", desc: "Waveform & energy ripple", color: "#ff8c1a", line: 3 }
    ]

    Repeater {
        model: root.modes
        delegate: Rectangle {
            width: root.width
            height: Math.round(112 * root.scale)
            radius: 10
            readonly property bool active: modelData.id === root.currentMode
            property color accentColor: modelData.color
            color: active ? Qt.rgba(accentColor.r, accentColor.g, accentColor.b, 0.08)
                          : Qt.rgba(2/255, 5/255, 7/255, 0.42)
            border.width: 1
            border.color: active ? Qt.rgba(accentColor.r, accentColor.g, accentColor.b, 0.42)
                                 : Qt.rgba(255/255, 126/255, 0, 0.19)

            AiCore {
                anchors.left: parent.left
                anchors.leftMargin: 14
                anchors.verticalCenter: parent.verticalCenter
                baseSize: Math.round(86 * root.scale)
                coreMode: modelData.id
                glowIntensity: active ? 0.70 : 0.45
                animated: false
            }

            Rectangle {
                anchors.left: parent.left
                anchors.leftMargin: Math.round(132 * root.scale)
                anchors.top: parent.top
                anchors.bottom: parent.bottom
                width: 1
                color: Qt.rgba(255/255, 126/255, 0, 0.12)
            }

            Column {
                anchors.left: parent.left
                anchors.leftMargin: Math.round(160 * root.scale)
                anchors.verticalCenter: parent.verticalCenter
                anchors.right: parent.right
                anchors.rightMargin: 18
                spacing: 11

                Text {
                    text: modelData.label
                    font.family: "Segoe UI"
                    font.pixelSize: Math.round(16 * root.scale)
                    font.bold: true
                    color: modelData.color
                }

                Text {
                    text: modelData.desc
                    font.family: "Segoe UI"
                    font.pixelSize: Math.round(12 * root.scale)
                    color: "#c8b8a8"
                }

                WaveLine {
                    width: parent.width
                    height: 20
                    accent: modelData.color
                    variant: modelData.line
                }
            }
        }
    }

    component WaveLine: Canvas {
        property color accent: "#ff8c1a"
        property int variant: 0

        onPaint: {
            var ctx = getContext("2d")
            if (!ctx) return
            var w = width, h = height
            ctx.clearRect(0, 0, w, h)
            ctx.strokeStyle = Qt.rgba(accent.r, accent.g, accent.b, 0.55)
            ctx.lineWidth = 1
            ctx.beginPath()
            for (var x = 0; x < w; x += 3) {
                var spike = Math.sin(x * 0.12 + variant) * Math.sin(x * 0.033 + variant * 2)
                var amp = (Math.abs(spike) > 0.72 || x > w * (0.66 + variant * 0.04)) ? 7 : 1.5
                var y1 = h / 2 - amp * Math.abs(spike)
                var y2 = h / 2 + amp * Math.abs(spike)
                ctx.moveTo(x, y1)
                ctx.lineTo(x, y2)
            }
            ctx.stroke()
        }
    }
}
