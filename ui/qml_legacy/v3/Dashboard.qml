import QtQuick 2.15
import QtQuick.Controls 2.15
import QtQuick.Layouts 1.15

Item {
    id: dashboard
    anchors.fill: parent

    property var bridge

    Theme { id: theme }

    // --- Background ---
    Rectangle {
        anchors.fill: parent
        color: theme.background
    }

    ParticleBackground {
        id: particleBackground
        anchors.fill: parent
        particleColor: theme.primary
    }

    // --- Main Layout ---
    Item {
        id: mainLayout
        anchors.fill: parent

        // --- Header ---
        Header {
            id: header
            anchors.top: parent.top
            anchors.left: parent.left
            anchors.right: parent.right
            height: theme.topBarHeight
        }

        // --- Sidebar ---
        Sidebar {
            id: sidebar
            anchors.left: parent.left
            anchors.top: header.bottom
            anchors.bottom: footer.top
            width: theme.sidebarWidth
            anchors.margins: 8
        }

        // --- Footer ---
        Footer {
            id: footer
            anchors.bottom: parent.bottom
            anchors.left: parent.left
            anchors.right: parent.right
            height: theme.bottomBarHeight
        }

        // --- Center Area ---
        Item {
            id: centerArea
            anchors.top: header.bottom
            anchors.bottom: footer.top
            anchors.left: sidebar.right
            anchors.right: rightPanel.left
            anchors.margins: 8

            // --- AI Core ---
            AiCore {
                id: aiCore
                anchors.centerIn: parent
                width: theme.coreSize
                height: theme.coreSize
            }
            
            // --- Voice Visualization ---
            VoiceVisualization {
                id: voiceVis
                anchors.top: aiCore.bottom
                anchors.topMargin: 20
                anchors.horizontalCenter: parent.horizontalCenter
                width: 300
            }

            // --- Subtitle Panel ---
            SubtitlePanel {
                id: subtitlePanel
                anchors.top: voiceVis.bottom
                anchors.topMargin: 20
                anchors.horizontalCenter: parent.horizontalCenter
                width: 500
            }
        }

        // --- Right Panel ---
        ColumnLayout {
            id: rightPanel
            anchors.right: parent.right
            anchors.top: header.bottom
            anchors.bottom: footer.top
            width: theme.rightPanelWidth
            anchors.margins: 8
            spacing: 8

            CoreStates {
                Layout.fillWidth: true
                Layout.preferredHeight: 450
            }

            QuickStatus {
                Layout.fillWidth: true
                Layout.fillHeight: true
            }
        }
    }
}
