import QtQuick 2.15

Rectangle {
    id: root

    property string coreMode: "idle"
    property string provider: "ElevenLabs"
    property string model: "Qwen 2.5 3B"
    property real cpuUsage: 0
    property real ramUsage: 0
    property real gpuUsage: 0
    property string currentTask: ""

    width: 590
    height: parent.height
    color: Qt.rgba(2/255, 3/255, 4/255, 0.42)
    border.width: 1
    border.color: Qt.rgba(255/255, 126/255, 0, 0.18)
    clip: true

    Column {
        anchors.fill: parent
        anchors.margins: 14
        spacing: 14

        Rectangle {
            width: parent.width
            height: Math.min(504, root.height * 0.50)
            radius: 14
            color: Qt.rgba(2/255, 5/255, 7/255, 0.52)
            border.width: 1
            border.color: Qt.rgba(255/255, 126/255, 0, 0.22)

            Text {
                id: stateTitle
                anchors.top: parent.top
                anchors.topMargin: 18
                anchors.left: parent.left
                anchors.leftMargin: 20
                text: "AI CORE STATES"
                font.family: "Segoe UI"
                font.pixelSize: 18
                font.bold: true
                color: "#ff8c1a"
            }

            AiCoreStates {
                anchors.top: stateTitle.bottom
                anchors.topMargin: 14
                anchors.left: parent.left
                anchors.leftMargin: 14
                anchors.right: parent.right
                anchors.rightMargin: 14
                currentMode: root.coreMode
                scale: root.width < 500 ? 0.82 : 1.0
            }
        }

        Rectangle {
            width: parent.width
            height: Math.min(250, root.height * 0.26)
            radius: 14
            color: Qt.rgba(2/255, 5/255, 7/255, 0.56)
            border.width: 1
            border.color: Qt.rgba(255/255, 126/255, 0, 0.24)

            Text {
                id: quickTitle
                anchors.top: parent.top
                anchors.topMargin: 16
                anchors.left: parent.left
                anchors.leftMargin: 20
                text: "QUICK STATUS"
                font.family: "Segoe UI"
                font.pixelSize: 16
                font.bold: true
                color: "#ff8c1a"
            }

            Column {
                anchors.left: parent.left
                anchors.leftMargin: 22
                anchors.top: quickTitle.bottom
                anchors.topMargin: 18
                width: parent.width * 0.50
                spacing: 17

                StatusRow { icon: "\u2630"; label: "INTERNET"; value: "Connected"; ok: true }
                StatusRow { icon: "\u266A"; label: "MICROPHONE"; value: "Active"; ok: true }
                StatusRow { icon: "\u25B7"; label: "VOICE PROVIDER"; value: root.provider; ok: true }
                StatusRow { icon: "\u25C8"; label: "LLM"; value: root.model; ok: true }
            }

            Column {
                anchors.right: parent.right
                anchors.rightMargin: 22
                anchors.top: quickTitle.bottom
                anchors.topMargin: 14
                width: parent.width * 0.34
                spacing: 13

                Meter { label: "CPU"; value: Math.round(root.cpuUsage) + "%"; progress: root.cpuUsage / 100; spark: true }
                Meter { label: "MEMORY"; value: Math.round(root.ramUsage) + "%"; progress: root.ramUsage / 100 }
                Meter { label: "GPU"; value: Math.round(root.gpuUsage) + "%"; progress: root.gpuUsage / 100 }
                Text {
                    text: "CLOCK      3.41 GHz"
                    font.family: "Segoe UI"
                    font.pixelSize: 13
                    color: "#d0c2b4"
                }
            }
        }

        Rectangle {
            width: parent.width
            height: Math.max(150, parent.height - 504 - 250 - 28)
            radius: 14
            color: Qt.rgba(2/255, 5/255, 7/255, 0.56)
            border.width: 1
            border.color: Qt.rgba(255/255, 126/255, 0, 0.24)

            Text {
                anchors.top: parent.top
                anchors.topMargin: 16
                anchors.left: parent.left
                anchors.leftMargin: 20
                text: "VOICE ACTIVITY VISUALIZATION"
                font.family: "Segoe UI"
                font.pixelSize: 16
                color: "#ead8c8"
            }

            VoicePanel {
                anchors.centerIn: parent
                anchors.verticalCenterOffset: 4
                width: parent.width - 70
                height: 78
                coreMode: root.coreMode
                micEnergy: 0.78
                assistantEnergy: 0.70
            }

            Text {
                anchors.left: parent.left
                anchors.leftMargin: 44
                anchors.bottom: parent.bottom
                anchors.bottomMargin: 18
                text: "YOU SPEAK\n(Listening)"
                font.family: "Segoe UI"
                font.pixelSize: 12
                color: "#ff8c1a"
            }

            Text {
                anchors.right: parent.right
                anchors.rightMargin: 44
                anchors.bottom: parent.bottom
                anchors.bottomMargin: 18
                horizontalAlignment: Text.AlignRight
                text: "JARVIS SPEAKS\n(Responding)"
                font.family: "Segoe UI"
                font.pixelSize: 12
                color: "#33aaff"
            }
        }
    }

    component StatusRow: Row {
        property string icon: ""
        property string label: ""
        property string value: ""
        property bool ok: false

        spacing: 12
        width: parent ? parent.width : 240
        height: 22

        Text { text: parent.icon; font.family: "Segoe UI"; font.pixelSize: 20; color: "#ff8c1a"; width: 22 }
        Text { text: parent.label; font.family: "Segoe UI"; font.pixelSize: 13; color: "#cfc0b2"; width: 118 }
        Rectangle { width: 7; height: 7; radius: 4; color: parent.ok ? "#22dd55" : "#3a3a3a"; anchors.verticalCenter: parent.verticalCenter }
        Text { text: parent.value; font.family: "Segoe UI"; font.pixelSize: 12; color: "#c2b4a8"; elide: Text.ElideRight; width: parent.width - 175 }
    }

    component Meter: Item {
        property string label: ""
        property string value: ""
        property real progress: 0
        property bool spark: false

        width: parent ? parent.width : 180
        height: 34

        Text {
            anchors.left: parent.left
            anchors.top: parent.top
            text: parent.label
            font.family: "Segoe UI"
            font.pixelSize: 13
            color: "#d9c9ba"
        }
        Text {
            anchors.right: parent.right
            anchors.top: parent.top
            text: parent.value
            font.family: "Segoe UI"
            font.pixelSize: 13
            color: "#e7d8ca"
        }
        Rectangle {
            anchors.left: parent.left
            anchors.right: parent.right
            anchors.bottom: parent.bottom
            height: 5
            radius: 2
            color: Qt.rgba(255/255, 255/255, 255/255, 0.08)
            Rectangle {
                anchors.left: parent.left
                anchors.top: parent.top
                anchors.bottom: parent.bottom
                width: parent.width * Math.max(0, Math.min(1, progress))
                radius: 2
                color: "#ff7e00"
            }
        }
    }
}
