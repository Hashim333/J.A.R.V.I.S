import QtQuick 2.15

/**
 * SystemCards — placeholder for system integration cards shown in the center area.
 * Currently displays status overview cards.
 */
Item {
    id: root

    property string coreMode: "idle"
    property real cpuUsage: 0
    property real ramUsage: 0

    // Simplified system status card
    Rectangle {
        anchors.centerIn: parent
        width: 200
        height: 80
        radius: 8
        color: Qt.rgba(255/255, 255/255, 255/255, 0.02)
        border.width: 1
        border.color: Qt.rgba(255/255, 140/255, 26/255, 0.06)

        visible: false // Hidden by default, can be toggled
    }
}