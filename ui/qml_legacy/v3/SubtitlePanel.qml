import QtQuick 2.15
import QtQuick.Controls 2.15

Rectangle {
    id: subtitlePanel
    width: 500
    height: 60
    color: theme.panelGlass
    border.color: theme.borderSubtle
    border.width: 1
    radius: 8

    Theme { id: theme }

    property string subtitle: bridge ? bridge.subtitle : "Initializing JARVIS..."

    Text {
        id: subtitleText
        anchors.centerIn: parent
        width: parent.width - 32
        text: subtitle
        font.pixelSize: 14
        color: theme.textPrimary
        wrapMode: Text.WordWrap
        horizontalAlignment: Text.AlignHCenter
        
        opacity: 0
        Behavior on opacity { NumberAnimation { duration: 300 } }
    }

    Timer {
        interval: 100; running: true
        onTriggered: {
            subtitleText.opacity = subtitle ? 1 : 0
        }
    }
}
