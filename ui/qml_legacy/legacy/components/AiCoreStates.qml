import QtQuick 2.15

Column {
    id: coreStatesRoot
    spacing: Math.round(6 * scale)

    property string currentMode: "idle"
    property real scale: 1.0

    readonly property var _modes: [
        { id: "idle", icon: "\u25CB", label: "Idle", desc: "Standing by, waiting for your request", color: "#777777" },
        { id: "listening", icon: "\u25B6", label: "Listening", desc: "Processing your voice input", color: "#33aaff" },
        { id: "thinking", icon: "\u2699", label: "Thinking", desc: "Analyzing context and forming response", color: "#ffd700" },
        { id: "speaking", icon: "\u266B", label: "Speaking", desc: "Delivering voice output", color: "#ff8c1a" }
    ]

    Repeater {
        model: _modes
        delegate: Rectangle {
            width: coreStatesRoot.width
            height: Math.round(44 * scale)
            radius: Math.round(8 * scale)
            color: {
                var isActive = modelData.id === coreStatesRoot.currentMode
                return isActive ? Qt.rgba(1, 0.55, 0.1, 0.06) : Qt.rgba(255, 255, 255, 0.015)
            }
            border.width: 1
            border.color: {
                var isActive = modelData.id === coreStatesRoot.currentMode
                return isActive ? Qt.rgba(1, 0.55, 0.1, 0.15) : Qt.rgba(1, 0.55, 0.1, 0.04)
            }
            Behavior on color { ColorAnimation { duration: 300 } }
            Behavior on border.color { ColorAnimation { duration: 300 } }

            Rectangle {
                anchors { left: parent.left; top: parent.top; bottom: parent.bottom }
                width: Math.round(3 * scale)
                radius: Math.round(1.5 * scale)
                color: modelData.color
                opacity: modelData.id === coreStatesRoot.currentMode ? 0.8 : 0.15
                Behavior on opacity { NumberAnimation { duration: 300 } }
            }

            Text {
                anchors { left: parent.left; leftMargin: Math.round(12 * scale); verticalCenter: parent.verticalCenter }
                text: modelData.icon
                color: modelData.id === coreStatesRoot.currentMode ? modelData.color : "#555544"
                font { pixelSize: Math.round(14 * scale); family: "Segoe UI" }
                opacity: modelData.id === coreStatesRoot.currentMode ? 1.0 : 0.5
                Behavior on color { ColorAnimation { duration: 300 } }
            }

            Column {
                anchors { left: parent.left; leftMargin: Math.round(34 * scale); verticalCenter: parent.verticalCenter }
                spacing: Math.round(1 * scale)
                Text {
                    text: modelData.label
                    color: modelData.id === coreStatesRoot.currentMode ? "#e0d5ca" : "#887766"
                    font { pixelSize: Math.round(10 * scale); bold: true; family: "Segoe UI" }
                    Behavior on color { ColorAnimation { duration: 300 } }
                }
                Text {
                    text: modelData.desc
                    color: "#776655"
                    font { pixelSize: Math.round(7 * scale); family: "Segoe UI" }
                    opacity: modelData.id === coreStatesRoot.currentMode ? 1.0 : 0.5
                    Behavior on opacity { NumberAnimation { duration: 300 } }
                }
            }
        }
    }
}
