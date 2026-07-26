import QtQuick 2.15
import QtQuick.Controls 2.15

Item {
    id: coreStatesRoot
    width: parent.width

    property string activeState: bridge ? bridge.coreState : "idle"

    Theme { id: theme }

    Component {
        id: stateCard
        Rectangle {
            width: coreStatesRoot.width
            height: 100
            border.color: theme.borderSubtle
            border.width: 1
            radius: 8

            property string stateName: "Idle"
            property bool isActive: false

            color: isActive ? Qt.rgba(theme.accentForMode(stateName.toLowerCase()).r, theme.accentForMode(stateName.toLowerCase()).g, theme.accentForMode(stateName.toLowerCase()).b, 0.1) : theme.panelGlass
            
            Behavior on color { ColorAnimation { duration: 300 } }

            Row {
                anchors.verticalCenter: parent.verticalCenter
                anchors.left: parent.left
                anchors.leftMargin: 16
                spacing: 12

                // Animated mini core placeholder
                Rectangle {
                    width: 40
                    height: 40
                    radius: 20
                    color: "transparent"
                    border.color: theme.accentForMode(stateName.toLowerCase())
                    border.width: 2
                    opacity: isActive ? 1.0 : 0.4
                    
                    Rectangle {
                        anchors.centerIn: parent
                        width: 20
                        height: 20
                        radius: 10
                        color: theme.accentForMode(stateName.toLowerCase())
                        opacity: isActive ? 0.8 : 0.3
                    }
                }

                Column {
                    spacing: 4
                    Text {
                        text: stateName.toUpperCase()
                        font.pixelSize: 12
                        font.bold: true
                        color: isActive ? theme.textPrimary : theme.textSecondary
                    }
                    Text {
                        text: isActive ? "ACTIVE" : "STANDBY"
                        font.pixelSize: 8
                        color: theme.textMuted
                        font.letterSpacing: 2
                    }
                }
            }

            // Waveform placeholder
            Rectangle {
                anchors.right: parent.right
                anchors.rightMargin: 16
                anchors.verticalCenter: parent.verticalCenter
                width: 80
                height: 30
                color: "transparent"
            }
        }
    }

    Column {
        id: statesColumn
        anchors.fill: parent
        spacing: 8
        
        Repeater {
            model: ["Idle", "Listening", "Thinking", "Speaking"]
            delegate: Loader {
                sourceComponent: stateCard
                width: parent.width
                onLoaded: {
                    item.stateName = modelData;
                    item.isActive = coreStatesRoot.activeState === modelData.toLowerCase();
                }

                Connections {
                    target: coreStatesRoot
                    function onActiveStateChanged() {
                        item.isActive = coreStatesRoot.activeState === item.stateName.toLowerCase()
                    }
                }
            }
        }
    }
    
    Timer {
        interval: 200; running: true; repeat: true
        onTriggered: {
            activeState = bridge ? bridge.coreState : "idle";
        }
    }
}
