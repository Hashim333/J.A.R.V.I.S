import QtQuick 2.15
import QtQuick.Window 2.15

Window {
    id: root
    objectName: "fullscreenWindow"
    title: "JARVIS"
    width: 1920
    height: 1080
    visible: true
    color: "#050505"
    flags: Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint

    Dashboard {
        id: dashboard
        anchors.fill: parent
        bridge: bridge // Pass the bridge to the dashboard
    }

    // Window dragging
    MouseArea {
        anchors.top: parent.top
        anchors.left: parent.left
        anchors.right: parent.right
        height: 28
        onPressed: { root.startSystemMove() }
        onDoubleClicked: {
            if (bridge) bridge.set_window_mode("floating_orb")
        }
    }
}
