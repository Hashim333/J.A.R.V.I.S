import QtQuick 2.15
import QtQuick.Window 2.15

Item {
    id: root

    width: parent.width
    height: 76
    z: 5

    MouseArea {
        anchors.fill: parent
        anchors.leftMargin: 280
        anchors.rightMargin: 140
        onPressed: {
            var w = Window.window
            if (w && !w.isWindowMaximized) w.startSystemMove()
        }
        onDoubleClicked: {
            var w = Window.window
            if (w && w.doToggleMax) w.doToggleMax()
        }
    }

    Rectangle {
        anchors.top: parent.top
        anchors.horizontalCenter: parent.horizontalCenter
        width: 276
        height: 72
        radius: 18
        color: Qt.rgba(4/255, 5/255, 7/255, 0.72)
        border.width: 1
        border.color: Qt.rgba(255/255, 126/255, 0, 0.28)

        Text {
            id: clockText
            anchors.top: parent.top
            anchors.topMargin: 12
            anchors.horizontalCenter: parent.horizontalCenter
            text: formatTime()
            font.family: "Segoe UI"
            font.pixelSize: 24
            color: "#d7c8ba"
        }

        Text {
            anchors.top: clockText.bottom
            anchors.topMargin: 0
            anchors.horizontalCenter: parent.horizontalCenter
            text: formatDate()
            font.family: "Segoe UI"
            font.pixelSize: 13
            color: "#9f8c7c"
        }
    }

    Row {
        anchors.right: parent.right
        anchors.rightMargin: 26
        anchors.top: parent.top
        anchors.topMargin: 18
        spacing: 23

        WindowButton {
            text: "-"
            onClicked: { var w = Window.window; if (w && w.doMinimize) w.doMinimize() }
        }
        WindowButton {
            text: "\u25A1"
            onClicked: { var w = Window.window; if (w && w.doMaximize) w.doMaximize() }
        }
        WindowButton {
            text: "X"
            isClose: true
            onClicked: { var w = Window.window; if (w && w.doClose) w.doClose() }
        }
    }

    Canvas {
        anchors.left: parent.left
        anchors.leftMargin: 254
        anchors.top: parent.top
        anchors.topMargin: 31
        width: 140
        height: 28
        opacity: 0.75
        onPaint: {
            var ctx = getContext("2d")
            if (!ctx) return
            ctx.clearRect(0, 0, width, height)
            ctx.strokeStyle = "#ff7e00"
            ctx.lineWidth = 1
            ctx.beginPath()
            for (var x = 0; x < width - 14; x += 4) {
                var amp = 2 + Math.abs(Math.sin(x * 0.23)) * 9
                ctx.moveTo(x, height / 2 - amp)
                ctx.lineTo(x, height / 2 + amp)
            }
            ctx.stroke()
            ctx.fillStyle = "#ff7e00"
            ctx.beginPath()
            ctx.arc(width - 8, height / 2, 3, 0, Math.PI * 2)
            ctx.fill()
        }
    }

    function formatTime() {
        var d = new Date()
        var hours = d.getHours()
        var suffix = hours >= 12 ? " PM" : " AM"
        hours = hours % 12
        if (hours === 0) hours = 12
        return hours.toString().padStart(2, "0") + ":" +
               d.getMinutes().toString().padStart(2, "0") + ":" +
               d.getSeconds().toString().padStart(2, "0") + suffix
    }

    function formatDate() {
        var d = new Date()
        var days = ["Sunday","Monday","Tuesday","Wednesday","Thursday","Friday","Saturday"]
        var months = ["January","February","March","April","May","June","July","August","September","October","November","December"]
        return days[d.getDay()] + ", " + months[d.getMonth()] + " " + d.getDate() + ", " + d.getFullYear()
    }

    Timer {
        interval: 1000
        running: true
        repeat: true
        onTriggered: clockText.text = formatTime()
    }

    component WindowButton: Rectangle {
        property string text: ""
        property bool isClose: false
        signal clicked()

        width: 20
        height: 20
        radius: 4
        color: "transparent"

        Text {
            anchors.centerIn: parent
            text: parent.text
            font.family: "Segoe UI"
            font.pixelSize: 18
            color: "#ff7e00"
        }

        MouseArea {
            anchors.fill: parent
            hoverEnabled: true
            cursorShape: Qt.PointingHandCursor
            onEntered: parent.color = isClose ? Qt.rgba(1, 0, 0, 0.16) : Qt.rgba(1, 0.49, 0, 0.14)
            onExited: parent.color = "transparent"
            onClicked: parent.clicked()
        }
    }
}
