import QtQuick 2.15

Rectangle {
    id: sidebarRoot

    property bool open: false
    Connections {
        target: typeof bridge !== "undefined" ? bridge : null
        function onSidebarVisibleChanged(v) { sidebarRoot.open = v }
    }

    // ── Sections (text icons only — no emoji) ────────────────────────
    property var sections: [
        { name: "Conversation", icon: ">>", active: true },
        { name: "Memory",      icon: "[]", active: true },
        { name: "Automation",  icon: "{}", active: true },
        { name: "Vision",      icon: "O",  active: true },
        { name: "Files",       icon: "#",  active: true },
        { name: "Settings",    icon: "*",  active: true },
        { name: "Developer",   icon: "/",  active: true },
    ]

    // ── Appearance ───────────────────────────────────────────────────
    color: Qt.rgba(10, 8, 6, 0.85)
    width: open ? 280 : 0
    Behavior on width { NumberAnimation { duration: 350; easing.type: Easing.OutCubic } }
    clip: true

    // ── Glass overlay ────────────────────────────────────────────────
    Rectangle {
        anchors.fill: parent
        color: Qt.rgba(1, 0.48, 0, 0.03)
    }

    // ── Right border glow ────────────────────────────────────────────
    Rectangle {
        anchors { right: parent.right; top: parent.top; bottom: parent.bottom }
        width: 1; color: Qt.rgba(1, 0.48, 0, 0.12); visible: parent.open
    }

    // ── Header ───────────────────────────────────────────────────────
    Text {
        id: headerText
        text: "JARVIS"
        color: "#ff7b00"
        font { pixelSize: 18; bold: true; letterSpacing: 4 }
        anchors { top: parent.top; topMargin: 28; left: parent.left; leftMargin: 24 }
        opacity: parent.open ? 1.0 : 0.0
        Behavior on opacity { NumberAnimation { duration: 250 } }
    }

    // ── Subtitle ─────────────────────────────────────────────────────
    Text {
        text: "C O N T R O L"
        color: "#555"
        font { pixelSize: 9; letterSpacing: 3 }
        anchors { top: headerText.bottom; topMargin: 2; left: parent.left; leftMargin: 26 }
        opacity: parent.open ? 0.6 : 0.0
        Behavior on opacity { NumberAnimation { duration: 250 } }
    }

    // ── Section list ─────────────────────────────────────────────────
    ListView {
        id: sectionList
        anchors { top: headerText.bottom; topMargin: 48; left: parent.left; right: parent.right; bottom: parent.bottom; margins: 10 }
        model: sections
        spacing: 4
        clip: true

        delegate: Rectangle {
            width: sectionList.width - 20; height: 40; radius: 8
            color: mouseArea.containsMouse ? Qt.rgba(1, 0.48, 0, 0.08) : "transparent"
            border.color: mouseArea.containsMouse ? Qt.rgba(1, 0.48, 0, 0.12) : "transparent"
            border.width: 1
            Behavior on color { ColorAnimation { duration: 150 } }

            Row {
                anchors { left: parent.left; leftMargin: 14; verticalCenter: parent.verticalCenter }
                spacing: 12
                Text {
                    text: modelData.icon
                    color: "#ff7b00"
                    font { pixelSize: 13; bold: true; family: "Consolas" }
                    opacity: 0.7
                }
                Text {
                    text: modelData.name
                    color: modelData.active ? "#cccccc" : "#444444"
                    font { pixelSize: 13; letterSpacing: 1 }
                }
                Rectangle {
                    visible: !modelData.active
                    height: 16; width: 36; radius: 8
                    color: Qt.rgba(1, 0.48, 0, 0.06); border.color: Qt.rgba(1, 0.48, 0, 0.12)
                    anchors.verticalCenter: parent.verticalCenter
                    Text { text: "Soon"; color: "#886644"; font.pixelSize: 9; anchors.centerIn: parent }
                }
            }

            MouseArea {
                id: mouseArea
                anchors.fill: parent; hoverEnabled: true
                onClicked: {
                    if (modelData.active && typeof bridge !== "undefined" && bridge)
                        bridge.set_sidebar_section(modelData.name.toLowerCase())
                }
            }
        }
    }

    // ── Toggle button ────────────────────────────────────────────────
    Rectangle {
        id: toggleBtn
        anchors { left: parent.right; top: parent.top; topMargin: 6 }
        width: 28; height: 28; radius: 6
        color: mouseOver.containsMouse ? Qt.rgba(1, 0.48, 0, 0.08) : "transparent"
        border.color: mouseOver.containsMouse ? Qt.rgba(1, 0.48, 0, 0.1) : "transparent"
        border.width: 1
        visible: !parent.open

        Text {
            text: ">"
            color: "#888"
            font.pixelSize: 14
            font.bold: true
            anchors.centerIn: parent
        }

        MouseArea {
            id: mouseOver
            anchors.fill: parent; hoverEnabled: true
            onClicked: { if (typeof bridge !== "undefined" && bridge) bridge.toggle_sidebar() }
        }
    }

    // ── Close button ─────────────────────────────────────────────────
    Text {
        anchors { top: parent.top; topMargin: 8; right: parent.right; rightMargin: 12 }
        text: "x"
        color: "#555"
        font.pixelSize: 16
        font.bold: true
        visible: parent.open
        MouseArea {
            anchors.fill: parent
            onClicked: { if (typeof bridge !== "undefined" && bridge) bridge.toggle_sidebar() }
        }
    }
}
