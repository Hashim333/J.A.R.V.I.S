import QtQuick 2.15

Item {
    id: root

    property real cpuUsage: 24
    property real ramUsage: 45
    property real gpuUsage: 18
    property real diskUsage: 32
    property real networkUsage: 68

    property var perfHistory: []
    readonly property int maxSamples: 42

    function recordSample() {
        if (perfHistory.length >= maxSamples)
            perfHistory.shift()
        perfHistory.push({
            cpu: cpuUsage,
            ram: ramUsage,
            gpu: gpuUsage,
            v: Math.max(4, Math.min(96, (cpuUsage + ramUsage + gpuUsage) / 3))
        })
        graphCanvas.requestPaint()
    }

    Timer {
        interval: 1000
        running: true
        repeat: true
        onTriggered: root.recordSample()
    }

    Rectangle {
        anchors.fill: parent
        radius: 12
        color: Qt.rgba(4/255, 8/255, 10/255, 0.58)
        border.width: 1
        border.color: Qt.rgba(255/255, 126/255, 0, 0.22)

        Column {
            anchors.fill: parent
            anchors.margins: 16
            spacing: 10

            Text {
                text: "SYSTEM OVERVIEW"
                font.family: "Segoe UI"
                font.pixelSize: 12
                color: "#ead8c8"
            }

            SysBar { label: "CPU"; value: Math.round(root.cpuUsage) + "%"; progress: root.cpuUsage / 100 }
            SysBar { label: "MEMORY"; value: Math.round(root.ramUsage) + "%"; progress: root.ramUsage / 100 }
            SysBar { label: "GPU"; value: Math.round(root.gpuUsage) + "%"; progress: root.gpuUsage / 100 }
            SysBar { label: "DISK"; value: Math.round(root.diskUsage) + "%"; progress: root.diskUsage / 100 }
            SysBar { label: "NETWORK"; value: Math.round(root.networkUsage) + "%"; progress: root.networkUsage / 100 }

            Text {
                text: "PERFORMANCE"
                font.family: "Segoe UI"
                font.pixelSize: 12
                color: "#ead8c8"
                topPadding: 5
            }

            Rectangle {
                width: parent.width
                height: 56
                radius: 4
                color: Qt.rgba(255/255, 126/255, 0, 0.035)
                border.width: 1
                border.color: Qt.rgba(255/255, 126/255, 0, 0.08)

                Canvas {
                    id: graphCanvas
                    anchors.fill: parent
                    anchors.margins: 2

                    onPaint: {
                        var ctx = getContext("2d")
                        if (!ctx) return
                        var w = width, h = height
                        ctx.clearRect(0, 0, w, h)
                        ctx.strokeStyle = Qt.rgba(1, 0.49, 0, 0.10)
                        ctx.lineWidth = 1
                        for (var gx = 0; gx < w; gx += 12) {
                            ctx.beginPath(); ctx.moveTo(gx, 0); ctx.lineTo(gx, h); ctx.stroke()
                        }
                        for (var gy = 0; gy < h; gy += 10) {
                            ctx.beginPath(); ctx.moveTo(0, gy); ctx.lineTo(w, gy); ctx.stroke()
                        }

                        var data = root.perfHistory
                        if (data.length < 2) return
                        var step = w / (data.length - 1)
                        ctx.strokeStyle = "#ff7e00"
                        ctx.lineWidth = 1.5
                        ctx.beginPath()
                        for (var i = 0; i < data.length; i++) {
                            var x = i * step
                            var y = h - (data[i].v / 100) * h
                            i === 0 ? ctx.moveTo(x, y) : ctx.lineTo(x, y)
                        }
                        ctx.stroke()
                    }
                }
            }

            Text {
                text: "All Systems Normal"
                font.family: "Segoe UI"
                font.pixelSize: 12
                color: "#cdb9a5"
            }
        }
    }

    component SysBar: Item {
        property string label: ""
        property string value: ""
        property real progress: 0

        width: parent ? parent.width : 200
        height: 22

        Text {
            anchors.left: parent.left
            anchors.top: parent.top
            text: parent.label
            font.family: "Segoe UI"
            font.pixelSize: 12
            color: "#b8aa9d"
        }

        Text {
            anchors.right: parent.right
            anchors.top: parent.top
            text: parent.value
            font.family: "Segoe UI"
            font.pixelSize: 12
            color: "#d6c9bd"
        }

        Rectangle {
            anchors.left: parent.left
            anchors.right: parent.right
            anchors.bottom: parent.bottom
            height: 4
            radius: 2
            color: Qt.rgba(255/255, 255/255, 255/255, 0.08)

            Rectangle {
                anchors.left: parent.left
                anchors.top: parent.top
                anchors.bottom: parent.bottom
                width: parent.width * Math.max(0, Math.min(1, progress))
                radius: 2
                color: "#ff7e00"
                Behavior on width { NumberAnimation { duration: 320; easing.type: Easing.OutCubic } }
            }
        }
    }
}
