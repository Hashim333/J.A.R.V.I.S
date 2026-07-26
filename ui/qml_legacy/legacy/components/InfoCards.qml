import QtQuick 2.15

Rectangle {
    id: infoRoot

    width: 200
    color: Qt.rgba(10, 8, 6, 0.7)
    radius: 0

    // ── Left accent border ────────────────────────────────────────────
    Rectangle {
        anchors { left: parent.left; top: parent.top; bottom: parent.bottom }
        width: 1; color: Qt.rgba(1, 0.48, 0, 0.08)
    }

    // ── Header ────────────────────────────────────────────────────────
    Text {
        id: headerLabel
        text: "SYSTEM"
        color: "#555"
        font { pixelSize: 9; letterSpacing: 3 }
        anchors { top: parent.top; topMargin: 14; left: parent.left; leftMargin: 16 }
    }

    // ── Info card template ────────────────────────────────────────────
    component InfoCard: Rectangle {
        property string cardLabel: ""
        property string cardValue: "--"
        property color cardAccent: "#ff7b00"

        width: infoRoot.width - 24; height: 48; radius: 8
        color: Qt.rgba(255, 255, 255, 0.03)
        anchors.horizontalCenter: parent.horizontalCenter

        Rectangle {
            anchors { left: parent.left; top: parent.top; bottom: parent.bottom }
            width: 2; radius: 1
            color: cardAccent; opacity: 0.4
        }

        Text {
            anchors { left: parent.left; leftMargin: 12; top: parent.top; topMargin: 6 }
            text: cardLabel
            color: "#888"
            font { pixelSize: 9; letterSpacing: 1 }
        }
        Text {
            anchors { left: parent.left; leftMargin: 12; bottom: parent.bottom; bottomMargin: 6 }
            text: cardValue
            color: "#e0e0e0"
            font { pixelSize: 13; weight: Font.DemiBold; family: "Consolas" }
        }
    }

    // ── CPU ───────────────────────────────────────────────────────────
    InfoCard {
        id: cpuCard
        anchors.top: headerLabel.bottom; anchors.topMargin: 10
        cardLabel: "CPU"
        cardAccent: "#33aaff"
        Connections {
            target: typeof bridge !== "undefined" ? bridge : null
            function onCpuUsageChanged(v) { cpuCard.cardValue = Number(v).toFixed(0) + "%" }
        }
    }

    // ── RAM ───────────────────────────────────────────────────────────
    InfoCard {
        id: ramCard
        anchors.top: cpuCard.bottom; anchors.topMargin: 6
        cardLabel: "RAM"
        cardAccent: "#00ff88"
        Connections {
            target: typeof bridge !== "undefined" ? bridge : null
            function onRamUsageChanged(v) { ramCard.cardValue = Number(v).toFixed(0) + "%" }
        }
    }

    // ── GPU ───────────────────────────────────────────────────────────
    InfoCard {
        id: gpuCard
        anchors.top: ramCard.bottom; anchors.topMargin: 6
        cardLabel: "GPU"
        cardAccent: "#ffd700"
        Connections {
            target: typeof bridge !== "undefined" ? bridge : null
            function onGpuUsageChanged(v) { gpuCard.cardValue = Number(v).toFixed(0) + "%" }
        }
    }

    // ── Battery ───────────────────────────────────────────────────────
    InfoCard {
        id: batCard
        anchors.top: gpuCard.bottom; anchors.topMargin: 6
        cardLabel: "Battery"
        cardAccent: "#ff7b00"
        visible: false
        Connections {
            target: typeof bridge !== "undefined" ? bridge : null
            function onBatteryChanged(v) {
                batCard.cardValue = Number(v).toFixed(0) + "%"
                batCard.visible = v >= 0
            }
        }
    }

    // ── Model info section ────────────────────────────────────────────
    Rectangle {
        anchors { top: batCard.bottom; topMargin: 16; left: parent.left; leftMargin: 12; right: parent.right; rightMargin: 12 }
        height: 1; color: Qt.rgba(1, 1, 1, 0.05)
    }

    Text {
        id: modelHeader
        text: "MODEL"
        color: "#555"
        font { pixelSize: 9; letterSpacing: 3 }
        anchors { top: parent.top; topMargin: 14; left: parent.left; leftMargin: 16 }
        visible: false
    }

    Text {
        id: providerValue
        anchors { top: infoRoot.top; topMargin: 200; left: parent.left; leftMargin: 16 }
        text: "Provider: --"
        color: "#999"
        font { pixelSize: 10; family: "Consolas" }
        Connections {
            target: typeof bridge !== "undefined" ? bridge : null
            function onProviderChanged(v) { providerValue.text = "Provider: " + v }
        }
    }

    Text {
        id: modelValue
        anchors { top: providerValue.bottom; topMargin: 4; left: parent.left; leftMargin: 16 }
        text: "Model: --"
        color: "#777"
        font { pixelSize: 10; family: "Consolas" }
        Connections {
            target: typeof bridge !== "undefined" ? bridge : null
            function onModelChanged(v) { modelValue.text = "Model: " + v }
        }
    }
}
