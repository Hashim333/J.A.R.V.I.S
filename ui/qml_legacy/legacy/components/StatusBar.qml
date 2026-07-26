import QtQuick 2.15

Rectangle {
    id: statusRoot

    height: 34
    color: Qt.rgba(10, 8, 6, 0.75)
    property bool _hasGlass: false

    // ── Status dot ───────────────────────────────────────────────────
    component Indicator: Item {
        width: childrenRect.width; height: parent.height
        property bool active: false
        property string labelText: ""

        Rectangle {
            id: dot; width: 6; height: 6; radius: 3
            anchors.verticalCenter: parent.verticalCenter
            color: parent.active ? "#00ff88" : "#333333"
            Behavior on color { ColorAnimation { duration: 300 } }
            Rectangle {
                anchors.centerIn: parent
                width: dot.width * 2.2; height: width; radius: width / 2
                color: dot.color; opacity: parent.active ? 0.3 : 0.0
                Behavior on opacity { NumberAnimation { duration: 300 } }
            }
        }
        Text {
            id: label
            anchors { left: dot.right; leftMargin: 6; verticalCenter: parent.verticalCenter }
            color: "#888888"; font.pixelSize: 10; font.family: "Consolas"
            text: parent.labelText
        }
    }

    // ── Left: status dots + clock ────────────────────────────────────
    Row {
        anchors { left: parent.left; leftMargin: 16; verticalCenter: parent.verticalCenter }
        spacing: 16

        Text {
            id: clockTxt
            color: "#cccccc"; font.family: "Consolas"; font.pixelSize: 12; font.bold: true
            text: "--:--:--"
            anchors.verticalCenter: parent.verticalCenter
            Connections {
                target: typeof bridge !== "undefined" ? bridge : null
                function onClockChanged(t) { clockTxt.text = t }
            }
        }

        Rectangle { width: 1; height: 16; color: "#2a2218"; anchors.verticalCenter: parent.verticalCenter }

        Indicator {
            id: internetDot; labelText: "Internet"
            Connections {
                target: typeof bridge !== "undefined" ? bridge : null
                function onInternetStatusChanged(v) { internetDot.active = v }
            }
        }
        Indicator {
            id: micDot; labelText: "Mic"
            Connections {
                target: typeof bridge !== "undefined" ? bridge : null
                function onMicStatusChanged(v) { micDot.active = v }
            }
        }
        Indicator {
            id: speakerDot; labelText: "Speaker"
            Connections {
                target: typeof bridge !== "undefined" ? bridge : null
                function onSpeakerStatusChanged(v) { speakerDot.active = v }
            }
        }
    }

    // ── Center: provider / model / task ──────────────────────────────
    Row {
        anchors.centerIn: parent
        spacing: 20
        visible: false
        Text { id: providerTxt; color: "#888"; font.pixelSize: 10; font.family: "Consolas"
            Connections { target: typeof bridge !== "undefined" ? bridge : null
                function onProviderChanged(v) { providerTxt.text = v; providerTxt.parent.parent.visible = !!v } } }
        Text { id: modelTxt; color: "#888"; font.pixelSize: 10; font.family: "Consolas"
            Connections { target: typeof bridge !== "undefined" ? bridge : null
                function onModelChanged(v) { modelTxt.text = v } } }
        Text { id: taskTxt; color: "#ff7b00"; font.pixelSize: 10; font.family: "Consolas"; font.bold: true
            Connections { target: typeof bridge !== "undefined" ? bridge : null
                function onCurrentTaskChanged(v) { taskTxt.text = v; taskTxt.parent.parent.visible = !!v } } }
    }

    // ── Right: mic level + CPU, RAM, GPU, Battery ────────────────────
    Row {
        anchors { right: parent.right; rightMargin: 16; verticalCenter: parent.verticalCenter }
        spacing: 16

        Item {
            id: micLevelItem
            width: 64; height: parent.height
            visible: false
            anchors.verticalCenter: parent.verticalCenter
            property real level: 0.0
            Connections {
                target: typeof bridge !== "undefined" ? bridge : null
                function onMicStatusChanged(v) { micLevelItem.visible = v }
                function onMicEnergyChanged(v) { micLevelItem.level = v }
            }
            Rectangle {
                width: 48; height: 4; radius: 2
                anchors.centerIn: parent
                color: "#222"
                Rectangle {
                    height: parent.height; radius: 2
                    anchors { left: parent.left; verticalCenter: parent.verticalCenter }
                    width: parent.width * Math.min(1.0, micLevelItem.level * 2.0)
                    color: Qt.rgba(0, 1, 0.53, 0.4 + micLevelItem.level * 0.6)
                }
            }
        }
        Text {
            id: cpuTxt; color: "#999"; font.family: "Consolas"; font.pixelSize: 10
            text: "CPU --%"
            Connections { target: typeof bridge !== "undefined" ? bridge : null
                function onCpuUsageChanged(v) { cpuTxt.text = "CPU " + Number(v).toFixed(0) + "%" } }
        }
        Text {
            id: ramTxt; color: "#999"; font.family: "Consolas"; font.pixelSize: 10
            text: "RAM --%"
            Connections { target: typeof bridge !== "undefined" ? bridge : null
                function onRamUsageChanged(v) { ramTxt.text = "RAM " + Number(v).toFixed(0) + "%" } }
        }
        Text {
            id: gpuTxt; color: "#999"; font.family: "Consolas"; font.pixelSize: 10
            text: "GPU --%"
            Connections { target: typeof bridge !== "undefined" ? bridge : null
                function onGpuUsageChanged(v) { gpuTxt.text = "GPU " + Number(v).toFixed(0) + "%" } }
        }
        Text {
            id: batTxt; color: "#999"; font.family: "Consolas"; font.pixelSize: 10
            visible: false
            text: "BAT --%"
            Connections { target: typeof bridge !== "undefined" ? bridge : null
                function onBatteryChanged(v) { batTxt.text = "BAT " + Number(v).toFixed(0) + "%"; batTxt.visible = v >= 0 } }
        }
    }
}
