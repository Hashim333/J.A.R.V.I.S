import QtQuick 2.15

Rectangle {
    id: root

    property string activeSection: "conversation"
    property bool internetOk: false
    property bool micOk: false
    property bool speakerOk: false
    property real cpuUsage: 0
    property real ramUsage: 0
    property real gpuUsage: 0

    signal sectionClicked(string section)

    width: 266
    height: parent.height
    color: Qt.rgba(3/255, 4/255, 5/255, 0.56)
    border.width: 1
    border.color: Qt.rgba(255/255, 126/255, 0, 0.15)
    clip: true

    Rectangle {
        anchors.fill: parent
        color: "transparent"
        border.width: 1
        border.color: Qt.rgba(255/255, 126/255, 0, 0.045)
        radius: 0
    }

    Item {
        id: logoArea
        anchors.top: parent.top
        anchors.topMargin: 18
        anchors.left: parent.left
        anchors.leftMargin: 26
        anchors.right: parent.right
        anchors.rightMargin: 20
        height: 66

        Text {
            id: brand
            text: "JARVIS"
            font.family: "Segoe UI"
            font.pixelSize: 30
            font.bold: true
            color: "#ff8200"
        }

        Text {
            anchors.top: brand.bottom
            anchors.topMargin: -2
            text: "AI ASSISTANT"
            font.family: "Segoe UI"
            font.pixelSize: 12
            color: "#d3b99f"
            opacity: 0.85
        }
    }

    Rectangle {
        id: navCard
        anchors.top: logoArea.bottom
        anchors.topMargin: 22
        anchors.left: parent.left
        anchors.leftMargin: 20
        anchors.right: parent.right
        anchors.rightMargin: 20
        height: Math.min(342, parent.height * 0.37)
        radius: 12
        color: Qt.rgba(2/255, 6/255, 8/255, 0.42)
        border.width: 1
        border.color: Qt.rgba(255/255, 126/255, 0, 0.22)

        Column {
            anchors.fill: parent
            anchors.margins: 13
            spacing: 4

            Repeater {
                model: [
                    { section: "home", icon: "\u2302", label: "HOME", soon: false },
                    { section: "conversation", icon: "\u25A1", label: "CONVERSATION", soon: false },
                    { section: "memory", icon: "\u25C7", label: "MEMORY", soon: false },
                    { section: "system", icon: "\u25AD", label: "SYSTEM", soon: false },
                    { section: "automation", icon: "\u2699", label: "AUTOMATION", soon: false },
                    { section: "agents", icon: "\u25CB", label: "AGENTS", soon: true },
                    { section: "settings", icon: "\u26ED", label: "SETTINGS", soon: false }
                ]

                Rectangle {
                    width: parent.width
                    height: 42
                    radius: 7
                    readonly property bool isActive: root.activeSection === modelData.section || (root.activeSection === "conversation" && modelData.section === "home")
                    color: isActive ? Qt.rgba(255/255, 126/255, 0, 0.14) : "transparent"
                    border.width: isActive ? 1 : 0
                    border.color: Qt.rgba(255/255, 126/255, 0, 0.18)

                    Rectangle {
                        anchors.left: parent.left
                        anchors.verticalCenter: parent.verticalCenter
                        width: 3
                        height: parent.height - 10
                        radius: 2
                        color: "#ff8c00"
                        opacity: parent.isActive ? 1 : 0
                    }

                    Row {
                        anchors.left: parent.left
                        anchors.leftMargin: 16
                        anchors.verticalCenter: parent.verticalCenter
                        spacing: 13

                        Text {
                            text: modelData.icon
                            font.family: "Segoe UI"
                            font.pixelSize: 20
                            color: parent.parent.isActive ? "#ff970d" : "#c9b7a4"
                            width: 22
                            horizontalAlignment: Text.AlignHCenter
                        }
                        Text {
                            text: modelData.label
                            font.family: "Segoe UI"
                            font.pixelSize: 14
                            color: parent.parent.isActive ? "#f4d7bd" : "#b5a493"
                            anchors.verticalCenter: parent.verticalCenter
                        }
                        Rectangle {
                            visible: modelData.soon
                            width: 34
                            height: 16
                            radius: 8
                            color: Qt.rgba(255/255, 126/255, 0, 0.12)
                            border.width: 1
                            border.color: Qt.rgba(255/255, 126/255, 0, 0.20)
                            Text {
                                anchors.centerIn: parent
                                text: "SOON"
                                font.family: "Segoe UI"
                                font.pixelSize: 8
                                color: "#eaa45e"
                            }
                        }
                    }

                    MouseArea {
                        anchors.fill: parent
                        hoverEnabled: true
                        cursorShape: Qt.PointingHandCursor
                        onClicked: root.sectionClicked(modelData.section)
                    }
                }
            }
        }
    }

    SystemCards {
        id: systemCards
        anchors.top: navCard.bottom
        anchors.topMargin: 22
        anchors.left: parent.left
        anchors.leftMargin: 20
        anchors.right: parent.right
        anchors.rightMargin: 20
        height: Math.min(310, parent.height - navCard.y - navCard.height - miniOrb.height - 56)
        cpuUsage: root.cpuUsage
        ramUsage: root.ramUsage
        gpuUsage: root.gpuUsage
    }

    Rectangle {
        id: miniOrb
        anchors.left: parent.left
        anchors.leftMargin: 0
        anchors.right: parent.right
        anchors.rightMargin: 0
        anchors.bottom: parent.bottom
        anchors.bottomMargin: 8
        height: 104
        radius: 28
        color: Qt.rgba(3/255, 5/255, 6/255, 0.70)
        border.width: 1
        border.color: Qt.rgba(255/255, 126/255, 0, 0.28)

        AiCore {
            anchors.left: parent.left
            anchors.leftMargin: 16
            anchors.verticalCenter: parent.verticalCenter
            baseSize: 72
            coreMode: "idle"
            glowIntensity: 0.45
            animated: false
        }

        Column {
            anchors.left: parent.left
            anchors.leftMargin: 102
            anchors.verticalCenter: parent.verticalCenter
            spacing: 3
            Text { text: "JARVIS"; font.family: "Segoe UI"; font.pixelSize: 12; color: "#d8c5b5" }
            Text { text: "Active"; font.family: "Segoe UI"; font.pixelSize: 11; color: "#00ff88" }
            Rectangle {
                width: 84; height: 1
                color: Qt.rgba(255/255, 126/255, 0, 0.45)
            }
        }

        Text {
            anchors.right: parent.right
            anchors.rightMargin: 18
            anchors.verticalCenter: parent.verticalCenter
            text: ">"
            font.family: "Segoe UI"
            font.pixelSize: 20
            color: "#d8a06b"
        }
    }
}
