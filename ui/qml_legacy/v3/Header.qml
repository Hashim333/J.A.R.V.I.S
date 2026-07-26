import QtQuick 2.15
import QtQuick.Controls 2.15

Item {
    id: header
    height: theme.topBarHeight
    width: parent.width

    Theme { id: theme }

    property string clockText: bridge ? bridge.clockText : "00:00"
    property string dateText: bridge ? bridge.dateText : "MON 01 JAN"
    property string version: "v3.0"
    property string statusText: "SYSTEM ONLINE"

    // Centered Clock and Date
    Row {
        anchors.centerIn: parent
        spacing: 24
        
        Text {
            text: clockText
            font.pixelSize: 12
            font.family: theme.fontMono
            color: theme.textPrimary
            font.letterSpacing: 2
        }
    }

    // Left Status
    Row {
        anchors.left: parent.left
        anchors.leftMargin: 24
        anchors.verticalCenter: parent.verticalCenter
        spacing: 12

        Rectangle {
            width: 8
            height: 8
            radius: 4
            color: theme.activeDot
            anchors.verticalCenter: parent.verticalCenter
        }
        Text {
            text: statusText
            font.pixelSize: 10
            font.family: theme.fontMono
            color: theme.textSecondary
            font.letterSpacing: 2
        }
        Text {
            text: version
            font.pixelSize: 10
            font.family: theme.fontMono
            color: theme.textMuted
            font.letterSpacing: 2
        }
    }

    // Right window controls
    Row {
        id: windowControls
        anchors.right: parent.right
        anchors.rightMargin: 16
        anchors.verticalCenter: parent.verticalCenter
        spacing: 8

        Repeater {
            model: ["—", "□", "✕"]
            delegate: Text {
                text: modelData
                font.pixelSize: 12
                color: theme.textSecondary
                opacity: mouseArea.containsMouse ? 1.0 : 0.7

                MouseArea {
                    id: mouseArea
                    anchors.fill: parent
                    hoverEnabled: true
                    onClicked: {
                        if (index === 0) bridge.minimizeWindow();
                        if (index === 1) bridge.maximizeWindow();
                        if (index === 2) bridge.closeWindow();
                    }
                }
            }
        }
    }
}
