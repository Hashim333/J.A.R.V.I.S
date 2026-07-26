import QtQuick 2.15
import QtQuick.Controls 2.15
import QtQuick.Layouts 1.15

Rectangle {
    id: sidebar
    width: theme.sidebarWidth
    color: theme.panelGlass
    radius: 16
    border.color: theme.borderSubtle
    border.width: 1

    Theme { id: theme }

    property int activeIndex: 0

    ColumnLayout {
        anchors.fill: parent
        anchors.margins: 8
        spacing: 20

        // --- Logo ---
        Item {
            Layout.fillWidth: true
            Layout.preferredHeight: 60
            Column {
                anchors.centerIn: parent
                spacing: 4
                Text {
                    text: "JARVIS"
                    font.pixelSize: 18
                    font.bold: true
                    color: theme.textPrimary
                    font.letterSpacing: 4
                    horizontalAlignment: Text.AlignHCenter
                }
                Text {
                    text: "AI OPERATING SYSTEM"
                    font.pixelSize: 8
                    color: theme.textSecondary
                    font.letterSpacing: 2
                    horizontalAlignment: Text.AlignHCenter
                }
            }
        }

        // --- Navigation ---
        ListView {
            id: listView
            Layout.fillWidth: true
            Layout.preferredHeight: 250
            model: [
                { "icon": "⬡", "name": "Dashboard" },
                { "icon": "◆", "name": "AI Settings" },
                { "icon": "◇", "name": "Memory & Context" },
                { "icon": "□", "name": "Connected Apps" },
                { "icon": "○", "name": "System Settings" }
            ]
            delegate: Item {
                width: listView.width
                height: 48
                property bool isCurrent: index === sidebar.activeIndex

                Rectangle {
                    anchors.fill: parent
                    color: isCurrent ? theme.accent : "transparent"
                    radius: 8
                    opacity: isCurrent ? 0.1 : (mouseArea.containsMouse ? 0.05 : 0)
                    Behavior on opacity { NumberAnimation { duration: 200 } }
                }

                Row {
                    anchors.verticalCenter: parent.verticalCenter
                    anchors.left: parent.left
                    anchors.leftMargin: 24
                    spacing: 16

                    Text {
                        text: modelData.icon
                        font.pixelSize: 16
                        color: isCurrent ? theme.accent : theme.textSecondary
                    }
                    Text {
                        text: modelData.name
                        font.pixelSize: 12
                        color: isCurrent ? theme.textPrimary : theme.textSecondary
                    }
                }

                MouseArea {
                    id: mouseArea
                    anchors.fill: parent
                    hoverEnabled: true
                    onClicked: sidebar.activeIndex = index
                }
            }
        }

        // Spacer
        Item {
            Layout.fillWidth: true
            Layout.fillHeight: true
        }

        // --- System Overview ---
        SystemOverview {
            Layout.fillWidth: true
            Layout.preferredHeight: 150
        }

        // --- Assistant Card ---
        Rectangle {
            Layout.fillWidth: true
            Layout.preferredHeight: 80
            color: theme.panelGlass
            radius: 8
            border.color: theme.borderSubtle
            border.width: 1

            // Content for assistant card
        }
    }
}
