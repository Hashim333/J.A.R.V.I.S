import QtQuick 2.15

Rectangle {
    id: root

    property real micEnergy: 0.0

    width: parent.width
    height: 64
    color: Qt.rgba(2/255, 4/255, 5/255, 0.76)
    border.width: 1
    border.color: Qt.rgba(255/255, 126/255, 0, 0.20)
    z: 4

    BottomCards {
        anchors.fill: parent
    }
}
