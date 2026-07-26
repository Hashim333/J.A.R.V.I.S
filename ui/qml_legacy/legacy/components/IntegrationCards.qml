import QtQuick 2.15

Rectangle {
    id: integRoot

    height: 64
    color: Qt.rgba(10, 8, 6, 0.7)

    // ── Top accent border ─────────────────────────────────────────────
    Rectangle {
        anchors { top: parent.top; left: parent.left; right: parent.right }
        height: 1; color: Qt.rgba(1, 0.48, 0, 0.08)
    }

    // ── Integration card template ─────────────────────────────────────
    component IntegCard: Rectangle {
        property string cardLabel: ""
        property bool cardActive: false
        property string cardMode: "idle"

        height: 40; radius: 8
        color: Qt.rgba(255, 255, 255, 0.03)
        border.color: cardActive ? Qt.rgba(1, 0.48, 0, 0.15) : Qt.rgba(255, 255, 255, 0.05)
        border.width: 1

        Rectangle {
            anchors { left: parent.left; top: parent.top; bottom: parent.bottom }
            width: 2; radius: 1
            color: cardActive ? "#00ff88" : "#444"
        }

        Text {
            anchors { left: parent.left; leftMargin: 10; verticalCenter: parent.verticalCenter }
            text: cardLabel
            color: cardActive ? "#aaaaaa" : "#555"
            font { pixelSize: 10; letterSpacing: 1 }
        }
    }

    // ── Cards row ─────────────────────────────────────────────────────
    Row {
        anchors { left: parent.left; leftMargin: 16; verticalCenter: parent.verticalCenter }
        spacing: 10

        IntegCard {
            id: micCard
            cardLabel: "Microphone"
            cardActive: false
            width: 120
            Connections {
                target: typeof bridge !== "undefined" ? bridge : null
                function onMicStatusChanged(v) { micCard.cardActive = v }
            }
        }

        IntegCard {
            id: speakerCard
            cardLabel: "Speaker"
            cardActive: false
            width: 100
            Connections {
                target: typeof bridge !== "undefined" ? bridge : null
                function onSpeakerStatusChanged(v) { speakerCard.cardActive = v }
            }
        }

        IntegCard {
            id: internetCard
            cardLabel: "Internet"
            cardActive: false
            width: 100
            Connections {
                target: typeof bridge !== "undefined" ? bridge : null
                function onInternetStatusChanged(v) { internetCard.cardActive = v }
            }
        }
    }

    // ── Right: current state badge ────────────────────────────────────
    Rectangle {
        anchors { right: parent.right; rightMargin: 16; verticalCenter: parent.verticalCenter }
        height: 28; width: 100; radius: 14
        color: Qt.rgba(1, 0.48, 0, 0.08)
        border.color: Qt.rgba(1, 0.48, 0, 0.12)
        border.width: 1

        Text {
            id: stateBadge
            anchors.centerIn: parent
            text: "idle"
            color: "#ff7b00"
            font { pixelSize: 10; letterSpacing: 2; bold: true }
        }

        Connections {
            target: typeof bridge !== "undefined" ? bridge : null
            function onCoreStateChanged(s) { stateBadge.text = s }
        }
    }
}
