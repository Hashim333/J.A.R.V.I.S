import QtQuick 2.15

Rectangle {
    id: navRoot

    width: 48
    color: Qt.rgba(10, 8, 6, 0.75)

    // ── Right accent border ───────────────────────────────────────────
    Rectangle {
        anchors { right: parent.right; top: parent.top; bottom: parent.bottom }
        width: 1; color: Qt.rgba(1, 0.48, 0, 0.12)
    }

    // ── Top icon ──────────────────────────────────────────────────────
    Rectangle {
        anchors { top: parent.top; topMargin: 10; horizontalCenter: parent.horizontalCenter }
        width: 28; height: 28; radius: 6
        color: Qt.rgba(1, 0.48, 0, 0.15)
        Text {
            anchors.centerIn: parent
            text: "J"
            color: "#ff7b00"
            font { pixelSize: 14; bold: true }
        }
    }

    // ── Nav items ─────────────────────────────────────────────────────
    property var items: [
        { icon: "○", label: "Home", section: "conversation" },
        { icon: "□", label: "Memory", section: "memory" },
        { icon: "△", label: "Automation", section: "automation" },
        { icon: "◇", label: "Files", section: "files" },
        { icon: "⚙", label: "Settings", section: "settings" },
    ]

    property string activeSection: "conversation"

    Column {
        anchors { top: parent.top; topMargin: 52; horizontalCenter: parent.horizontalCenter }
        spacing: 4
        Repeater {
            model: items
            Rectangle {
                width: 36; height: 36; radius: 8
                color: navRoot.activeSection === modelData.section ? Qt.rgba(1, 0.48, 0, 0.12) : "transparent"
                border.color: navRoot.activeSection === modelData.section ? Qt.rgba(1, 0.48, 0, 0.15) : "transparent"
                border.width: 1
                Behavior on color { ColorAnimation { duration: 150 } }

                Text {
                    anchors.centerIn: parent
                    text: modelData.icon
                    color: navRoot.activeSection === modelData.section ? "#ff7b00" : "#666666"
                    font.pixelSize: 14
                }

                MouseArea {
                    anchors.fill: parent; hoverEnabled: true
                    onClicked: {
                        navRoot.activeSection = modelData.section
                        if (typeof bridge !== "undefined" && bridge)
                            bridge.set_sidebar_section(modelData.section)
                    }
                }
            }
        }
    }
}
