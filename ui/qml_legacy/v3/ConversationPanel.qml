import QtQuick 2.15
import QtQuick.Controls 2.15

Rectangle {
    id: conversationPanel
    color: theme.panelGlass
    border.color: theme.borderSubtle
    border.width: 1
    radius: 8

    Theme { id: theme }

    property string userQuery: bridge ? bridge.lastUserQuery : "What is the weather like?"
    property string assistantResponse: bridge ? bridge.lastAssistantResponse : "I'm sorry, I can't provide real-time weather information."

    Column {
        anchors.fill: parent
        anchors.margins: 16
        spacing: 12

        Text {
            text: "LAST INTERACTION"
            font.pixelSize: 10
            color: theme.textSecondary
            font.letterSpacing: 3
        }

        // User Query
        Row {
            spacing: 8
            Text {
                text: "You:"
                font.pixelSize: 10
                font.bold: true
                color: theme.textPrimary
            }
            Text {
                text: userQuery
                font.pixelSize: 10
                color: theme.textSecondary
                elide: Text.ElideRight
                width: parent.width - 40
            }
        }

        // Assistant Response
        Row {
            spacing: 8
            Text {
                text: "JARVIS:"
                font.pixelSize: 10
                font.bold: true
                color: theme.accent
            }
            Text {
                text: assistantResponse
                font.pixelSize: 10
                color: theme.textSecondary
                elide: Text.ElideRight
                width: parent.width - 60
            }
        }
    }
}
