import QtQuick 2.15
import QtQuick.Window 2.15

/**
 * Header — top bar with clock, date, and window controls.
 * Uses Window.window attached property to control the parent window.
 */
Rectangle {
    id: root

    width: parent.width
    height: 28
    color: "transparent"
    z: 5

    // Top accent lines
    Rectangle {
        y: 0; width: parent.width; height: 1
        color: "#57320B"; opacity: 0.85
    }
    Rectangle {
        y: 1; width: parent.width; height: 1
        color: "#120b04"
    }

    // ── Window drag area ──
    MouseArea {
        anchors.fill: parent
        anchors.rightMargin: 120
        onPressed: {
            var w = Window.window
            if (w && !w.isWindowMaximized) w.startSystemMove()
        }
        onDoubleClicked: {
            var w = Window.window
            if (w && w.doToggleMax) w.doToggleMax()
        }
        cursorShape: Qt.OpenHandCursor
    }

    // ── Clock ──
    Text {
        id: clockText
        anchors.left: parent.left
        anchors.leftMargin: 24
        anchors.verticalCenter: parent.verticalCenter
        text: {
            var d = new Date()
            return d.getHours().toString().padStart(2, '0') + ":" +
                   d.getMinutes().toString().padStart(2, '0') + ":" +
                   d.getSeconds().toString().padStart(2, '0')
        }
        font.family: "Consolas"
        font.pixelSize: 12
        color: Qt.rgba(207/255, 195/255, 186/255, 0.6)
    }

    // ── Date ──
    Text {
        anchors.left: parent.left
        anchors.leftMargin: 90
        anchors.verticalCenter: parent.verticalCenter
        text: {
            var d = new Date()
            var days = ["Sunday","Monday","Tuesday","Wednesday","Thursday","Friday","Saturday"]
            var months = ["January","February","March","April","May","June",
                          "July","August","September","October","November","December"]
            return days[d.getDay()] + ", " + months[d.getMonth()] + " " + d.getDate() + ", " + d.getFullYear()
        }
        font.family: "Segoe UI"
        font.pixelSize: 8
        color: Qt.rgba(143/255, 131/255, 123/255, 0.4)
    }

    // ── Window Controls ──
    Row {
        anchors.right: parent.right
        anchors.rightMargin: 16
        anchors.verticalCenter: parent.verticalCenter
        spacing: 14

        WindowButton {
            text: "−"
            onClicked: { var w = Window.window; if (w && w.doMinimize) w.doMinimize() }
        }
        WindowButton {
            text: "□"
            onClicked: { var w = Window.window; if (w && w.doMaximize) w.doMaximize() }
        }
        WindowButton {
            text: "✕"
            isClose: true
            onClicked: { var w = Window.window; if (w && w.doClose) w.doClose() }
        }
    }

    // ── Timer for clock update ──
    Timer {
        interval: 1000; running: true; repeat: true
        onTriggered: {
            var d = new Date()
            clockText.text = d.getHours().toString().padStart(2, '0') + ":" +
                             d.getMinutes().toString().padStart(2, '0') + ":" +
                             d.getSeconds().toString().padStart(2, '0')
        }
    }

    // ── Window Button Component ──
    component WindowButton: Rectangle {
        property string text: ""
        property bool isClose: false
        signal clicked()

        width: 22; height: 22; radius: 11
        color: "transparent"
        Behavior on color { ColorAnimation { duration: 150 } }

        Text {
            anchors.centerIn: parent
            text: parent.text
            font.family: "Segoe UI"
            font.pixelSize: 12; font.bold: true
            color: Qt.rgba(255/255, 140/255, 26/255, 0.50)
        }

        MouseArea {
            anchors.fill: parent
            hoverEnabled: true
            cursorShape: Qt.PointingHandCursor
            onEntered: {
                parent.color = isClose
                    ? Qt.rgba(255/255, 26/255, 26/255, 0.20)
                    : Qt.rgba(255/255, 140/255, 26/255, 0.15)
            }
            onExited: parent.color = "transparent"
            onClicked: parent.clicked()
        }
    }
}