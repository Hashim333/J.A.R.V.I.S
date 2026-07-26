import QtQuick 2.15
import QtQuick.Controls 2.15
import QtQuick.Layouts 1.15

Rectangle {
    id: quickStatusRoot
    width: parent.width
    color: theme.panelGlass
    border.color: theme.borderSubtle
    border.width: 1
    radius: 8

    Theme { id: theme }

    property int internetStatus: bridge ? bridge.internetStatus : 1
    property int micStatus: bridge ? bridge.micStatus : 1
    property string provider: bridge ? bridge.provider : "openai"
    property string modelName: bridge ? bridge.modelName : "gpt-4"
    property real cpuUsage: bridge ? bridge.cpuUsage : 23
    property real ramUsage: bridge ? bridge.ramUsage : 45
    property real gpuUsage: bridge ? bridge.gpuUsage : 12

    Component {
        id: statusItem
        Item {
            width: quickStatusRoot.width / 2 - 16
            height: 40
            
            property string label: "STATUS"
            property string value: "OK"
            property color indicatorColor: theme.activeDot

            Row {
                anchors.verticalCenter: parent.verticalCenter
                spacing: 8
                Rectangle {
                    width: 6
                    height: 6
                    radius: 3
                    color: indicatorColor
                }
                Column {
                    spacing: 2
                    Text {
                        text: label
                        font.pixelSize: 8
                        color: theme.textMuted
                        font.letterSpacing: 2
                    }
                    Text {
                        text: value
                        font.pixelSize: 10
                        font.bold: true
                        color: theme.textSecondary
                    }
                }
            }
        }
    }
    
    Component {
        id: usageBar
        Item {
            width: quickStatusRoot.width - 32
            height: 20

            property string label: "USAGE"
            property real value: 0.5
            property color barColor: theme.primary

            Column {
                spacing: 4
                Text {
                    text: label
                    font.pixelSize: 8
                    color: theme.textMuted
                    font.letterSpacing: 2
                }
                Rectangle {
                    width: parent.width
                    height: 4
                    radius: 2
                    color: theme.panelDark

                    Rectangle {
                        width: parent.width * value
                        height: 4
                        radius: 2
                        color: barColor
                    }
                }
            }
        }
    }

    ColumnLayout {
        anchors.fill: parent
        anchors.margins: 16

        Text {
            text: "QUICK STATUS"
            font.pixelSize: 10
            color: theme.textSecondary
            font.letterSpacing: 3
            Layout.alignment: Qt.AlignHCenter
        }
        
        GridLayout {
            columns: 2
            
            Loader { sourceComponent: statusItem; onLoaded: { item.label = "Internet"; item.value = internetStatus ? "Online" : "Offline"; item.indicatorColor = internetStatus ? theme.activeDot : theme.errorColor } }
            Loader { sourceComponent: statusItem; onLoaded: { item.label = "Microphone"; item.value = micStatus ? "Active" : "Inactive"; item.indicatorColor = micStatus ? theme.micDot : theme.inactiveDot } }
            Loader { sourceComponent: statusItem; onLoaded: { item.label = "Provider"; item.value = provider.toUpperCase() } }
            Loader { sourceComponent: statusItem; onLoaded: { item.label = "LLM Model"; item.value = modelName } }
        }

        Loader { sourceComponent: usageBar; onLoaded: { item.label = "CPU USAGE"; item.value = cpuUsage / 100; item.barColor = "#4488ff" } }
        Loader { sourceComponent: usageBar; onLoaded: { item.label = "MEMORY USAGE"; item.value = ramUsage / 100; item.barColor = "#44ff88" } }
        Loader { sourceComponent: usageBar; onLoaded: { item.label = "GPU USAGE"; item.value = gpuUsage / 100; item.barColor = "#ffaa44" } }
    }
}
