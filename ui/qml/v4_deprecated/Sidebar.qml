import QtQuick 2.15

/**
 * Sidebar — 200px dark glass sidebar with logo, navigation, and status dots.
 */
Rectangle {
    id: root

    property string activeSection: "conversation"
    property bool internetOk: false
    property bool micOk: false
    property bool speakerOk: false

    signal sectionClicked(string section)

    width: 200
    height: parent.height
    color: Qt.rgba(8/255, 6/255, 5/255, 0.85)
    clip: true

    // Right border divider
    Rectangle {
        anchors.right: parent.right
        width: 1
        height: parent.height
        color: Qt.rgba(255/255, 140/255, 26/255, 0.08)
    }

    // ── Logo Area ──
    Item {
        id: logoArea
        anchors.top: parent.top
        anchors.topMargin: 20
        anchors.left: parent.left
        anchors.leftMargin: 20
        width: parent.width
        height: 60

        Rectangle {
            id: logoIcon
            width: 32
            height: 32
            radius: 8
            color: Qt.rgba(255/255, 140/255, 26/255, 0.12)
            border.width: 1
            border.color: Qt.rgba(255/255, 140/255, 26/255, 0.15)

            Text {
                anchors.centerIn: parent
                text: "J"
                font.pixelSize: 16
                font.bold: true
                color: "#ff8c1a"
            }
        }

        Text {
            anchors.left: logoIcon.right
            anchors.leftMargin: 12
            anchors.top: logoIcon.top
            anchors.topMargin: -2
            text: "JARVIS"
            font.family: "Segoe UI"
            font.pixelSize: 16
            font.bold: true
            font.letterSpacing: 3
            color: "#e8d5c4"
        }

        Text {
            anchors.left: logoIcon.right
            anchors.leftMargin: 12
            anchors.top: logoIcon.top
            anchors.topMargin: 20
            text: "AI ASSISTANT"
            font.family: "Segoe UI"
            font.pixelSize: 8
            font.letterSpacing: 4
            color: "#776655"
        }
    }

    // ── Divider ──
    Rectangle {
        anchors.top: logoArea.bottom
        anchors.topMargin: 0
        anchors.horizontalCenter: parent.horizontalCenter
        width: parent.width - 40
        height: 1
        color: Qt.rgba(255/255, 140/255, 26/255, 0.06)
    }

    // ── Navigation Items ──
    Column {
        id: navColumn
        anchors.top: logoArea.bottom
        anchors.topMargin: 14
        anchors.left: parent.left
        anchors.leftMargin: 12
        anchors.right: parent.right
        anchors.rightMargin: 12
        spacing: 2

        Repeater {
            model: [
                { section: "conversation", icon: "◉", label: "Conversation" },
                { section: "memory",       icon: "▦", label: "Memory" },
                { section: "automation",   icon: "⚙", label: "Automation" },
                { section: "files",        icon: "◈", label: "Files" },
                { section: "settings",     icon: "⚡", label: "Settings" }
            ]

            Item {
                width: parent.width
                height: 40

                // Active indicator bar
                Rectangle {
                    anchors.left: parent.left
                    anchors.leftMargin: -12
                    anchors.verticalCenter: parent.verticalCenter
                    width: 3
                    height: parent.height * 0.6
                    radius: 1.5
                    color: "#ff8c1a"
                    opacity: root.activeSection === modelData.section ? 1 : 0
                    visible: opacity > 0
                    Behavior on opacity { NumberAnimation { duration: 200 } }
                }

                Rectangle {
                    anchors.fill: parent
                    radius: 8
                    color: root.activeSection === modelData.section
                           ? Qt.rgba(255/255, 140/255, 26/255, 0.08)
                           : "transparent"
                    Behavior on color { ColorAnimation { duration: 150 } }

                    Row {
                        anchors.left: parent.left
                        anchors.leftMargin: 12
                        anchors.verticalCenter: parent.verticalCenter
                        spacing: 10

                        Text {
                            text: modelData.icon
                            font.pixelSize: 14
                            color: root.activeSection === modelData.section ? "#ff8c1a" : "#665544"
                            Behavior on color { ColorAnimation { duration: 150 } }
                            anchors.verticalCenter: parent.verticalCenter
                        }

                        Text {
                            text: modelData.label
                            font.family: "Segoe UI"
                            font.pixelSize: 12
                            font.letterSpacing: 1
                            color: root.activeSection === modelData.section ? "#e8d5c4" : "#776655"
                            Behavior on color { ColorAnimation { duration: 150 } }
                            anchors.verticalCenter: parent.verticalCenter
                        }
                    }

                    MouseArea {
                        anchors.fill: parent
                        hoverEnabled: true
                        cursorShape: Qt.PointingHandCursor
                        onEntered: {
                            if (root.activeSection !== modelData.section) {
                                parent.color = Qt.rgba(255/255, 140/255, 26/255, 0.08)
                            }
                        }
                        onExited: {
                            if (root.activeSection !== modelData.section) {
                                parent.color = "transparent"
                            }
                        }
                        onClicked: root.sectionClicked(modelData.section)
                    }
                }
            }
        }
    }

    // ── Status Section ──
    Item {
        anchors.bottom: parent.bottom
        anchors.bottomMargin: 16
        anchors.left: parent.left
        anchors.leftMargin: 20
        anchors.right: parent.right
        anchors.rightMargin: 20
        height: 30

        Column {
            spacing: 6

            Row {
                spacing: 8
                anchors.horizontalCenter: parent.horizontalCenter

                // Network status
                Rectangle {
                    width: 5; height: 5; radius: 2.5
                    anchors.verticalCenter: parent.verticalCenter
                    color: root.internetOk ? "#00ff88" : "#333333"
                }
                Text {
                    text: "Net"
                    font.family: "Consolas"
                    font.pixelSize: 8
                    color: "#776655"
                    anchors.verticalCenter: parent.verticalCenter
                }

                // Mic status
                Rectangle {
                    width: 5; height: 5; radius: 2.5
                    anchors.verticalCenter: parent.verticalCenter
                    color: root.micOk ? "#33aaff" : "#333333"
                }
                Text {
                    text: "Mic"
                    font.family: "Consolas"
                    font.pixelSize: 8
                    color: "#776655"
                    anchors.verticalCenter: parent.verticalCenter
                }

                // Speaker status
                Rectangle {
                    width: 5; height: 5; radius: 2.5
                    anchors.verticalCenter: parent.verticalCenter
                    color: root.speakerOk ? "#ff8c1a" : "#333333"
                }
                Text {
                    text: "Spk"
                    font.family: "Consolas"
                    font.pixelSize: 8
                    color: "#776655"
                    anchors.verticalCenter: parent.verticalCenter
                }
            }
        }
    }
}