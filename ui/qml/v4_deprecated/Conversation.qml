import QtQuick 2.15
import QtQuick.Controls 2.15

/**
 * Conversation — scrollable conversation history panel.
 * Reads history directly from bridge.conversationHistory.
 * Notified of changes via conversationHistoryChanged signal (see Dashboard Connections).
 */
Rectangle {
    id: root

    property int msgCount: 0

    width: 760
    height: 174
    radius: 14
    color: Qt.rgba(3/255, 6/255, 8/255, 0.62)
    border.width: 1
    border.color: Qt.rgba(255/255, 126/255, 0, 0.32)

    // ── Title ──
    Text {
        id: titleLabel
        anchors.top: parent.top; anchors.topMargin: 18
        anchors.left: parent.left; anchors.leftMargin: 28
        text: "CONVERSATION  \u266A"
        font.family: "Segoe UI"; font.pixelSize: 16
        color: "#ead8c8"
    }

    // ── Entry count ──
    Text {
        id: countText
        anchors.top: parent.top; anchors.topMargin: 18
        anchors.right: parent.right; anchors.rightMargin: 28
        text: "\u2299"
        font.family: "Segoe UI"; font.pixelSize: 16
        color: "#ff8c1a"
    }

    // ── Empty placeholder ──
    Text {
        id: emptyLabel
        anchors.left: parent.left
        anchors.leftMargin: 88
        anchors.verticalCenter: parent.verticalCenter
        text: "JARVIS\nOpening Chrome for you."
        font.family: "Segoe UI"; font.pixelSize: 14
        lineHeight: 1.45
        color: "#f0d5bb"
        visible: root.msgCount === 0
    }

    AiCore {
        anchors.left: parent.left
        anchors.leftMargin: 28
        anchors.verticalCenter: parent.verticalCenter
        baseSize: 34
        coreMode: "idle"
        glowIntensity: 0.45
        animated: false
        visible: root.msgCount === 0
    }

    // ── ListView ──
    ListView {
        id: listView
        anchors.top: titleLabel.bottom; anchors.topMargin: 16
        anchors.left: parent.left; anchors.leftMargin: 18
        anchors.right: parent.right; anchors.rightMargin: 18
        anchors.bottom: parent.bottom; anchors.bottomMargin: 14
        clip: true
        spacing: 6
        visible: root.msgCount > 0

        model: bridge && bridge.conversationHistory ? bridge.conversationHistory : []

        delegate: Rectangle {
            width: listView.width - 16
            height: msgText.implicitHeight + 22
            radius: 8
            color: modelData.speaker === "USER"
                   ? Qt.rgba(51/255, 170/255, 255/255, 0.06)
                   : Qt.rgba(255/255, 140/255, 26/255, 0.06)

            Rectangle {
                anchors.left: parent.left; anchors.top: parent.top
                anchors.bottom: parent.bottom
                width: 3; radius: 1.5
                color: modelData.speaker === "USER" ? "#33aaff" : "#ff8c1a"
            }

            Text {
                id: speakerLabel
                anchors.top: parent.top; anchors.topMargin: 6
                anchors.left: parent.left; anchors.leftMargin: 12
                text: modelData.speaker === "USER" ? "YOU" : "JARVIS"
                font.family: "Segoe UI"; font.pixelSize: 8
                font.bold: true; font.letterSpacing: 1
                color: modelData.speaker === "USER" ? "#33aaff" : "#ff8c1a"
            }

            Text {
                anchors.top: parent.top; anchors.topMargin: 6
                anchors.right: parent.right; anchors.rightMargin: 10
                text: modelData.timestamp || ""
                font.family: "Consolas"; font.pixelSize: 7
                color: "#555544"
            }

            Text {
                id: msgText
                anchors.top: speakerLabel.bottom; anchors.topMargin: 4
                anchors.left: parent.left; anchors.leftMargin: 12
                anchors.right: parent.right; anchors.rightMargin: 10
                text: modelData.text || ""
                font.family: "Segoe UI"; font.pixelSize: 12
                color: "#e0c4a6"
                wrapMode: Text.WordWrap
            }
        }

        onCountChanged: {
            if (count > 0) positionViewAtEnd()
        }
    }

    // ── Refresh from bridge (called by Dashboard Connections) ──
    function refresh() {
        var hist = bridge && bridge.conversationHistory ? bridge.conversationHistory : []
        root.msgCount = hist.length
        // Force listView model re-evaluation
        listView.model = hist
    }
}
