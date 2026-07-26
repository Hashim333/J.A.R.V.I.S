import QtQuick 2.15

/**
 * Conversation — subtitle panel showing JARVIS's spoken text.
 */
Rectangle {
    id: root

    property string subtitleText: ""
    property string coreMode: "idle"

    width: 500
    height: 40
    radius: 8
    color: Qt.rgba(5/255, 6/255, 7/255, 0.70)
    border.width: 1
    border.color: Qt.rgba(255/255, 140/255, 26/255, 0.12)

    opacity: subtitleText.length > 0 ? 1 : 0
    Behavior on opacity { NumberAnimation { duration: 500 } }

    Text {
        id: subText
        anchors.centerIn: parent
        text: root.subtitleText
        font.family: "Segoe UI"
        font.pixelSize: 11
        color: "#e0c4a6"
        horizontalAlignment: Text.AlignHCenter
        elide: Text.ElideRight
        maximumLineCount: 1
        width: parent.width - 24
    }
}