import QtQuick 2.15

Item {
    id: root

    width: parent.width
    height: parent.height

    Row {
        anchors.fill: parent
        anchors.leftMargin: 88
        anchors.rightMargin: 88
        spacing: Math.max(18, (width - 760) / 5)

        Repeater {
            model: [
                { icon: "\u25CE", label: "ADAPTIVE UI", subtext: "Orange (AI) \u2192 Blue (You)", accent: "#ff8c1a" },
                { icon: "\u25C8", label: "REAL-TIME VOICE MATCH", subtext: "Particles react to voice", accent: "#33aaff" },
                { icon: "\u25A3", label: "SMOOTH 60 FPS", subtext: "GPU Accelerated", accent: "#ff8c1a" },
                { icon: "\u25C9", label: "NO CLUTTER", subtext: "Focus on what matters", accent: "#ff8c1a" },
                { icon: "\u2723", label: "PREMIUM & FUTURISTIC", subtext: "Next-Gen AI Experience", accent: "#ff8c1a" }
            ]

            Item {
                width: Math.max(150, (parent.width - parent.spacing * 4) / 5)
                height: parent.height

                Row {
                    anchors.centerIn: parent
                    spacing: 12

                    Rectangle {
                        width: 34
                        height: 34
                        radius: 8
                        color: Qt.rgba(255/255, 126/255, 0, 0.08)
                        border.width: 1
                        border.color: Qt.rgba(accentColor.r, accentColor.g, accentColor.b, 0.35)

                        property color accentColor: modelData.accent

                        Text {
                            anchors.centerIn: parent
                            text: modelData.icon
                            font.family: "Segoe UI"
                            font.pixelSize: 17
                            color: modelData.accent
                        }
                    }

                    Column {
                        anchors.verticalCenter: parent.verticalCenter
                        spacing: 2

                        Text {
                            text: modelData.label
                            font.family: "Segoe UI"
                            font.pixelSize: 13
                            color: "#d9c9ba"
                        }

                        Text {
                            text: modelData.subtext
                            font.family: "Segoe UI"
                            font.pixelSize: 11
                            color: "#9a8b7d"
                        }
                    }
                }
            }
        }
    }
}
