import QtQuick 2.15

/**
 * BottomCards — preview cards in the bottom section (Always Accessible, Chrome, VS Code, Floating Orb, Taskbar).
 */
Item {
    id: root

    width: parent.width
    height: parent.height

    Row {
        anchors.left: parent.left
        anchors.leftMargin: 20
        anchors.verticalCenter: parent.verticalCenter
        spacing: 20

        Repeater {
            model: [
                { icon: "◉", label: "ALWAYS\nACCESSIBLE", accent: "#ff8c1a" },
                { icon: "◈", label: "CHROME", accent: "#33aaff" },
                { icon: "▣", label: "VS CODE", accent: "#00ff88" },
                { icon: "◎", label: "FLOATING\nORB", accent: "#ffd700" },
                { icon: "▬", label: "TASKBAR", accent: "#ff8c1a" }
            ]

            Item {
                width: 100
                height: 48

                Rectangle {
                    anchors.fill: parent
                    radius: 6
                    color: Qt.rgba(255/255, 255/255, 255/255, 0.02)
                    border.width: 1
                    border.color: Qt.rgba(255/255, 255/255, 255/255, 0.04)
                    Behavior on color { ColorAnimation { duration: 150 } }
                    Behavior on border.color { ColorAnimation { duration: 150 } }

                    Column {
                        anchors.centerIn: parent
                        spacing: 4

                        Text {
                            anchors.horizontalCenter: parent.horizontalCenter
                            text: modelData.icon
                            font.pixelSize: 16
                            color: modelData.accent
                        }

                        Text {
                            anchors.horizontalCenter: parent.horizontalCenter
                            text: modelData.label
                            font.family: "Segoe UI"
                            font.pixelSize: 7
                            font.letterSpacing: 1
                            color: "#998877"
                            horizontalAlignment: Text.AlignHCenter
                            lineHeight: 1.2
                        }
                    }

                    MouseArea {
                        anchors.fill: parent
                        hoverEnabled: true
                        cursorShape: Qt.PointingHandCursor
                        onEntered: {
                            parent.color = Qt.rgba(255/255, 140/255, 26/255, 0.06)
                            parent.border.color = Qt.rgba(255/255, 140/255, 26/255, 0.10)
                        }
                        onExited: {
                            parent.color = Qt.rgba(255/255, 255/255, 255/255, 0.02)
                            parent.border.color = Qt.rgba(255/255, 255/255, 255/255, 0.04)
                        }
                    }
                }
            }
        }
    }
}