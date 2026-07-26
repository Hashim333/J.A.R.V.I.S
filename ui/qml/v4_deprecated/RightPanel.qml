import QtQuick 2.15

/**
 * RightPanel — 240px panel with core state, quick status (CPU/RAM/GPU), and active task.
 */
Rectangle {
    id: root

    property string coreMode: "idle"
    property string provider: "ElevenLabs"
    property string model: "Qwen 2.5 3B"
    property real cpuUsage: 0
    property real ramUsage: 0
    property real gpuUsage: 0
    property string currentTask: ""

    width: 240
    height: parent.height
    color: Qt.rgba(8/255, 6/255, 5/255, 0.85)
    clip: true

    // Left border divider
    Rectangle {
        anchors.left: parent.left
        width: 1
        height: parent.height
        color: Qt.rgba(255/255, 140/255, 26/255, 0.08)
    }

    // ── Header ──
    Text {
        anchors.top: parent.top
        anchors.topMargin: 18
        anchors.left: parent.left
        anchors.leftMargin: 18
        text: "JARVIS"
        font.family: "Segoe UI"
        font.pixelSize: 18
        font.bold: true
        font.letterSpacing: 3
        color: "#e8d5c4"
    }
    Text {
        anchors.top: parent.top
        anchors.topMargin: 42
        anchors.left: parent.left
        anchors.leftMargin: 20
        text: "AI ASSISTANT"
        font.family: "Segoe UI"
        font.pixelSize: 9
        font.letterSpacing: 4
        color: "#776655"
    }

    // ── Divider ──
    Rectangle {
        anchors.top: parent.top
        anchors.topMargin: 70
        anchors.horizontalCenter: parent.horizontalCenter
        width: parent.width - 36
        height: 1
        color: Qt.rgba(255/255, 140/255, 26/255, 0.06)
    }

    // Timer for pulse animation
    property real animTick: 0
    Timer {
        interval: 50
        running: true
        repeat: true
        onTriggered: { root.animTick = Date.now() }
    }

    // ── CORE STATE Section ──
    Text {
        anchors.top: parent.top
        anchors.topMargin: 84
        anchors.left: parent.left
        anchors.leftMargin: 18
        text: "CORE STATE"
        font.family: "Segoe UI"
        font.pixelSize: 7
        font.letterSpacing: 3
        color: "#776655"
    }

    // Core State Card
    Rectangle {
        anchors.top: parent.top
        anchors.topMargin: 100
        anchors.left: parent.left
        anchors.leftMargin: 16
        anchors.right: parent.right
        anchors.rightMargin: 16
        height: 52
        radius: 8
        color: Qt.rgba(255/255, 255/255, 255/255, 0.03)
        border.width: 1
        border.color: Qt.rgba(255/255, 140/255, 26/255, 0.10)

        // State dot
        Rectangle {
            anchors.left: parent.left
            anchors.leftMargin: 12
            anchors.verticalCenter: parent.verticalCenter
            width: 8; height: 8; radius: 4
            color: {
                switch (root.coreMode) {
                    case "listening": return "#33aaff"
                    case "thinking":  return "#ffd700"
                    case "speaking":  return "#ff8c1a"
                    case "error":     return "#ff3355"
                    case "offline":   return "#444444"
                    default:          return "#ff8c1a"
                }
            }
            Behavior on color { ColorAnimation { duration: 500; easing.type: Easing.OutCubic } }

            // Pulse animation
            Rectangle {
                anchors.centerIn: parent
                width: parent.width + 6
                height: parent.height + 6
                radius: (width + height) / 4
                color: "transparent"
                border.width: 1
                border.color: Qt.rgba(parent.color.r, parent.color.g, parent.color.b, 0.3)
                opacity: 0.5 + 0.5 * Math.sin(root.animTick * 0.003)
            }
        }

        // State name
        Text {
            anchors.left: parent.left
            anchors.leftMargin: 28
            anchors.verticalCenter: parent.verticalCenter
            anchors.verticalCenterOffset: -6
            text: root.coreMode.charAt(0).toUpperCase() + root.coreMode.slice(1)
            font.family: "Segoe UI"
            font.pixelSize: 11
            font.bold: true
            color: "#e0d5ca"
        }

        // Model name
        Text {
            anchors.left: parent.left
            anchors.leftMargin: 28
            anchors.verticalCenter: parent.verticalCenter
            anchors.verticalCenterOffset: 10
            text: root.model
            font.family: "Consolas"
            font.pixelSize: 8
            color: "#998877"
        }

        // Provider badge
        Rectangle {
            anchors.right: parent.right
            anchors.rightMargin: 8
            anchors.verticalCenter: parent.verticalCenter
            width: 60
            height: 20
            radius: 4
            color: Qt.rgba(255/255, 140/255, 26/255, 0.06)
            Text {
                anchors.centerIn: parent
                text: root.provider
                font.family: "Consolas"
                font.pixelSize: 7
                color: "#aa8866"
            }
        }
    }

    // ── QUICK STATUS Section ──
    Text {
        anchors.top: parent.top
        anchors.topMargin: 168
        anchors.left: parent.left
        anchors.leftMargin: 18
        text: "QUICK STATUS"
        font.family: "Segoe UI"
        font.pixelSize: 7
        font.letterSpacing: 3
        color: "#776655"
    }

    // Status Cards
    Column {
        anchors.top: parent.top
        anchors.topMargin: 184
        anchors.left: parent.left
        anchors.leftMargin: 16
        anchors.right: parent.right
        anchors.rightMargin: 16
        spacing: 6

        // CPU
        StatusCard {
            label: "CPU"
            value: Math.round(root.cpuUsage) + "%"
            progress: root.cpuUsage / 100
            accentColor: "#33aaff"
        }

        // RAM
        StatusCard {
            label: "RAM"
            value: Math.round(root.ramUsage) + "%"
            progress: root.ramUsage / 100
            accentColor: "#00ff88"
        }

        // GPU
        StatusCard {
            label: "GPU"
            value: Math.round(root.gpuUsage) + "%"
            progress: root.gpuUsage / 100
            accentColor: "#ffd700"
        }
    }

    // ── Active Task Panel ──
    Rectangle {
        anchors.bottom: parent.bottom
        anchors.bottomMargin: 16
        anchors.left: parent.left
        anchors.leftMargin: 16
        anchors.right: parent.right
        anchors.rightMargin: 16
        height: root.currentTask.length > 0 ? 40 : 0
        radius: 6
        color: Qt.rgba(255/255, 255/255, 255/255, 0.03)
        border.width: 1
        border.color: Qt.rgba(255/255, 140/255, 26/255, 0.06)
        visible: height > 0
        clip: true

        Behavior on height { NumberAnimation { duration: 300; easing.type: Easing.OutCubic } }

        Text {
            anchors.top: parent.top
            anchors.topMargin: 4
            anchors.left: parent.left
            anchors.leftMargin: 8
            text: "CURRENT TASK"
            font.family: "Segoe UI"
            font.pixelSize: 6
            font.letterSpacing: 2
            color: "#776655"
        }

        Text {
            anchors.bottom: parent.bottom
            anchors.bottomMargin: 4
            anchors.left: parent.left
            anchors.leftMargin: 8
            anchors.right: parent.right
            anchors.rightMargin: 8
            text: root.currentTask
            font.family: "Consolas"
            font.pixelSize: 9
            color: "#e0d5ca"
            elide: Text.ElideRight
        }
    }

    // ── Status Card Component ──
    component StatusCard: Rectangle {
        property string label: ""
        property string value: ""
        property real progress: 0
        property color accentColor: "#33aaff"

        height: 40
        radius: 6
        color: Qt.rgba(255/255, 255/255, 255/255, 0.03)
        border.width: 1
        border.color: Qt.rgba(255/255, 140/255, 26/255, 0.06)

        // Left accent
        Rectangle {
            anchors.left: parent.left
            anchors.top: parent.top
            anchors.bottom: parent.bottom
            width: 2
            radius: 1
            color: accentColor
        }

        // Label
        Text {
            anchors.left: parent.left
            anchors.leftMargin: 12
            anchors.verticalCenter: parent.verticalCenter
            text: parent.label
            font.family: "Segoe UI"
            font.pixelSize: 7
            font.letterSpacing: 1
            color: "#998877"
        }

        // Value
        Text {
            anchors.right: parent.right
            anchors.rightMargin: 8
            anchors.verticalCenter: parent.verticalCenter
            text: parent.value
            font.family: "Consolas"
            font.pixelSize: 10
            font.weight: Font.DemiBold
            color: "#e0e0e0"
        }

        // Progress bar
        Rectangle {
            anchors.left: parent.left
            anchors.leftMargin: 12
            anchors.right: parent.right
            anchors.rightMargin: 50
            anchors.verticalCenter: parent.verticalCenter
            anchors.verticalCenterOffset: 8
            height: 3
            radius: 1.5
            color: Qt.rgba(255/255, 255/255, 255/255, 0.06)

            Rectangle {
                anchors.left: parent.left
                anchors.top: parent.top
                anchors.bottom: parent.bottom
                width: parent.width * parent.parent.progress
                radius: 1.5
                color: accentColor
                Behavior on width { NumberAnimation { duration: 300; easing.type: Easing.OutCubic } }
            }
        }
    }
}