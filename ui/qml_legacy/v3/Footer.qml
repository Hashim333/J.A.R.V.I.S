import QtQuick 2.15
import QtQuick.Controls 2.15
import QtQuick.Layouts 1.15

Rectangle {
    id: footer
    width: parent.width
    height: theme.bottomBarHeight
    color: theme.panelGlass
    border.color: theme.borderSubtle
    border.width: 1

    Theme { id: theme }

    RowLayout {
        anchors.fill: parent
        anchors.margins: 8
        spacing: 8

        // Taskbar Preview (Placeholder)
        Rectangle {
            id: taskbarPreview
            color: theme.panelDark
            radius: 8
            Layout.preferredWidth: 200
            Layout.fillHeight: true
        }

        // Integration Cards
        IntegrationCards {
            id: integrationCards
            Layout.fillWidth: true
            Layout.fillHeight: true
        }

        // Conversation Panel
        ConversationPanel {
            id: conversationPanel
            Layout.preferredWidth: 300
            Layout.fillHeight: true
        }

        // Voice Visualization
        VoiceVisualization {
            id: voiceVisualization
            Layout.preferredWidth: 200
            Layout.fillHeight: true
        }

        // Floating Orb
        FloatingOrb {
            id: floatingOrb
            Layout.preferredWidth: 100
            Layout.fillHeight: true
        }
    }
}
