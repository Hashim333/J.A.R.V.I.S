import QtQuick 2.15
import QtQuick.Controls 2.15

Item {
    id: integrationCardsRoot

    Theme { id: theme }

    property var integrations: [
        { name: "Google Chrome", icon: "🌐", status: "Active" },
        { name: "VS Code", icon: "💻", status: "Active" },
        { name: "Spotify", icon: "🎵", status: "Inactive" },
        { name: "File Explorer", icon: "📁", status: "Active" }
    ]

    Component {
        id: integrationCard
        Rectangle {
            width: 150
            height: integrationCardsRoot.height
            color: theme.panelGlass
            border.color: theme.borderSubtle
            border.width: 1
            radius: 8

            property string integrationName: "Integration"
            property string icon: "❓"
            property string status: "Unknown"

            Column {
                anchors.centerIn: parent
                spacing: 8
                
                Text {
                    text: icon
                    font.pixelSize: 24
                    anchors.horizontalCenter: parent.horizontalCenter
                }
                
                Text {
                    text: integrationName
                    font.pixelSize: 10
                    color: theme.textSecondary
                    anchors.horizontalCenter: parent.horizontalCenter
                }
                
                Text {
                    text: status.toUpperCase()
                    font.pixelSize: 8
                    color: status === "Active" ? theme.activeDot : theme.inactiveDot
                    font.letterSpacing: 2
                    anchors.horizontalCenter: parent.horizontalCenter
                }
            }
        }
    }

    ListView {
        id: listView
        anchors.fill: parent
        orientation: ListView.Horizontal
        spacing: 8
        model: integrationCardsRoot.integrations
        delegate: Loader {
            sourceComponent: integrationCard
            onLoaded: {
                item.integrationName = modelData.name
                item.icon = modelData.icon
                item.status = modelData.status
            }
        }
    }
}
