import QtQuick 2.15
import QtQuick.Window 2.15
import QtQuick.Controls 2.15
import "components"

Window {
    id: root
    objectName: "fullscreenWindow"

    visibility: Window.FullScreen
    color: "#000000"

    // ── Bridge properties ─────────────────────────────────────────────
    property string currentMode: (typeof bridge !== "undefined" && bridge) ? bridge.coreState : "idle"
    property string subtitleText: "Yes Hashim, I'm listening. How can I help you?"
    property real micLevel: 0.35
    property real assistantLevel: 0.28
    property real cpu: 24
    property real ram: 45
    property real gpu: 18
    property bool internetOk: true
    property bool micOk: true
    property bool speakerOk: true
    property string provider: "ElevenLabs"
    property string modelName: "Qwen 2.5 3B"
    property string clockText: "--:--:--"
    property string activeTask: ""

    // ── Responsive scaling (base: 1920×1080) ──────────────────────────
    readonly property real refW: 1920
    readonly property real refH: 1080
    readonly property real scaleW: root.width / refW
    readonly property real scaleH: root.height / refH
    readonly property real s: Math.min(scaleW, scaleH)

    readonly property real sidebarW: Math.round(200 * s)
    readonly property int sidebarMinW: 160
    readonly property real rightPanelW: Math.round(240 * s)
    readonly property int rightPanelMinW: 200
    readonly property real bottomBarH: Math.round(64 * s)
    readonly property int bottomBarMinH: 50
    readonly property real bottomPreviewH: Math.round(48 * s)
    readonly property real coreSize: Math.min(root.width * 0.135, root.height * 0.24, 300)
    readonly property real topBarH: Math.round(28 * s)

    // ── Bridge connections ───────────────────────────────────────────
    Connections {
        target: typeof bridge !== "undefined" ? bridge : null
        function onCoreStateChanged(m) { root.currentMode = m }
        function onSubtitleChanged(t) { root.subtitleText = t && t.length ? t : "Yes Hashim, I'm listening. How can I help you?" }
        function onMicEnergyChanged(e) { root.micLevel = Math.max(0.05, e) }
        function onAssistantEnergyChanged(e) { root.assistantLevel = Math.max(0.05, e) }
        function onCpuUsageChanged(v) { root.cpu = v }
        function onRamUsageChanged(v) { root.ram = v }
        function onGpuUsageChanged(v) { root.gpu = v }
        function onInternetStatusChanged(v) { root.internetOk = v }
        function onMicStatusChanged(v) { root.micOk = v }
        function onSpeakerStatusChanged(v) { root.speakerOk = v }
        function onProviderChanged(v) { if (v) root.provider = v }
        function onModelChanged(v) { if (v) root.modelName = v }
        function onClockChanged(t) { root.clockText = t }
        function onCurrentTaskChanged(t) { root.activeTask = t }
        function onWindowModeChanged(m) { root.handleWindowMode(m) }
    }

    function requestWindowMode(mode) {
        if (typeof bridge !== "undefined" && bridge) bridge.set_window_mode(mode)
    }

    function handleWindowMode(mode) {
        if (mode === "fullscreen") {
            root.visibility = Window.FullScreen
            orbWindow.visible = false
            dockWindow.visible = false
        } else if (mode === "floating_orb") {
            root.visibility = Window.Hidden
            orbWindow.visible = true
            dockWindow.visible = false
        } else if (mode === "edge_dock") {
            root.visibility = Window.Hidden
            orbWindow.visible = false
            dockWindow.visible = true
        } else if (mode === "system_tray") {
            root.visibility = Window.Hidden
            orbWindow.visible = false
            dockWindow.visible = false
        }
    }

    Timer {
        interval: 80
        running: true
        repeat: true
        onTriggered: {
            if (root.currentMode === "listening") {
                root.micLevel = Math.max(root.micLevel, 0.25 + Math.random() * 0.65)
            } else if (root.currentMode === "speaking") {
                root.assistantLevel = Math.max(root.assistantLevel, 0.25 + Math.random() * 0.65)
            } else {
                root.micLevel = Math.max(0.08, root.micLevel * 0.92)
                root.assistantLevel = Math.max(0.08, root.assistantLevel * 0.92)
            }
        }
    }

    // ==================================================================
    // FULLSCREEN BACKGROUND
    // ==================================================================
    Rectangle {
        anchors.fill: parent
        color: "#000000"

        // Deep space radial gradient
        Rectangle {
            anchors.centerIn: parent
            width: parent.width * 1.2
            height: parent.height * 1.35
            radius: width / 2
            gradient: Gradient {
                GradientStop { position: 0.0; color: "#0d0905" }
                GradientStop { position: 0.45; color: "#040506" }
                GradientStop { position: 1.0; color: "#010101" }
            }
        }

        // Orange ambient glow field (pulsing)
        Rectangle {
            id: ambientGlow
            anchors.centerIn: parent
            width: parent.width * 0.65
            height: width
            radius: width / 2
            opacity: 0.35
            gradient: Gradient {
                GradientStop { position: 0.0; color: "#4a2100" }
                GradientStop { position: 0.35; color: "#160900" }
                GradientStop { position: 1.0; color: "transparent" }
            }
            NumberAnimation on opacity {
                from: 0.32; to: 0.42; duration: 3000
                loops: Animation.Infinite; running: true
                easing.type: Easing.InOutSine
            }
        }

        // Blue listening ambient
        Rectangle {
            anchors.centerIn: parent
            width: parent.width * 0.55
            height: width
            radius: width / 2
            opacity: root.currentMode === "listening" ? 0.18 : 0.0
            Behavior on opacity { NumberAnimation { duration: 600 } }
            gradient: Gradient {
                GradientStop { position: 0.0; color: "#002244" }
                GradientStop { position: 0.4; color: "#001122" }
                GradientStop { position: 1.0; color: "transparent" }
            }
        }

        // Gold thinking ambient
        Rectangle {
            anchors.centerIn: parent
            width: parent.width * 0.45
            height: width
            radius: width / 2
            opacity: root.currentMode === "thinking" ? 0.12 : 0.0
            Behavior on opacity { NumberAnimation { duration: 600 } }
            gradient: Gradient {
                GradientStop { position: 0.0; color: "#332200" }
                GradientStop { position: 0.5; color: "#1a1100" }
                GradientStop { position: 1.0; color: "transparent" }
            }
        }
    }

    // ── Top accent lines ──────────────────────────────────────────────
    Rectangle {
        anchors { left: parent.left; right: parent.right; top: parent.top }
        height: 1
        color: "#57320B"
        opacity: 0.85
    }
    Rectangle {
        anchors { left: parent.left; right: parent.right; top: parent.top; topMargin: 1 }
        height: 1
        color: "#120b04"
    }

    // ── Top bar: Clock + Date + Window controls ───────────────────────
    Item {
        anchors { left: parent.left; right: parent.right; top: parent.top; topMargin: 2 }
        height: topBarH

        Text {
            text: root.clockText
            color: "#cfc3ba"
            font.pixelSize: Math.round(12 * s)
            font.family: "Consolas"
            anchors { left: parent.left; leftMargin: Math.round(24 * s); verticalCenter: parent.verticalCenter }
            opacity: 0.6
        }
        Text {
            text: Qt.formatDate(new Date(), "dddd, MMMM d, yyyy")
            color: "#8f837b"
            font.pixelSize: Math.round(8 * s)
            font.family: "Segoe UI"
            anchors { left: parent.left; leftMargin: Math.round(90 * s); verticalCenter: parent.verticalCenter; verticalCenterOffset: 1 }
            opacity: 0.4
        }

        Row {
            anchors { top: parent.top; topMargin: Math.round(6 * s); right: parent.right; rightMargin: Math.round(16 * s) }
            spacing: Math.round(14 * s)
            z: 10

            Rectangle {
                width: Math.round(22 * s); height: width; radius: width / 2
                color: mouseMin.containsMouse ? Qt.rgba(1, 0.55, 0.1, 0.15) : "transparent"
                Text {
                    anchors.centerIn: parent
                    text: "\u2212"
                    color: Qt.rgba(1, 0.55, 0.1, 0.5)
                    font.pixelSize: Math.round(14 * s)
                }
                MouseArea {
                    id: mouseMin
                    anchors.fill: parent; hoverEnabled: true
                    onClicked: root.requestWindowMode("floating_orb")
                }
            }
            Rectangle {
                width: Math.round(22 * s); height: width; radius: width / 2
                color: mouseMax.containsMouse ? Qt.rgba(1, 0.55, 0.1, 0.15) : "transparent"
                Text {
                    anchors.centerIn: parent
                    text: "\u25A1"
                    color: Qt.rgba(1, 0.55, 0.1, 0.5)
                    font.pixelSize: Math.round(10 * s)
                }
                MouseArea {
                    id: mouseMax
                    anchors.fill: parent; hoverEnabled: true
                }
            }
            Rectangle {
                width: Math.round(22 * s); height: width; radius: width / 2
                color: mouseClose.containsMouse ? Qt.rgba(1, 0.1, 0.1, 0.2) : "transparent"
                Text {
                    anchors.centerIn: parent
                    text: "\u2715"
                    color: Qt.rgba(1, 0.55, 0.1, 0.5)
                    font.pixelSize: Math.round(10 * s)
                }
                MouseArea {
                    id: mouseClose
                    anchors.fill: parent; hoverEnabled: true
                    onClicked: Qt.quit()
                }
            }
        }
    }

    // ==================================================================
    // MAIN LAYOUT (sidebar | center | right)
    // ==================================================================
    Item {
        anchors { left: parent.left; right: parent.right; top: parent.top; topMargin: topBarH; bottom: parent.bottom; bottomMargin: bottomBarH }

        // ── LEFT SIDEBAR ──────────────────────────────────────────────
        Rectangle {
            id: leftSidebar
            anchors { left: parent.left; top: parent.top; bottom: parent.bottom }
            width: Math.max(sidebarW, sidebarMinW)
            color: Qt.rgba(8, 6, 5, 0.88)

            Rectangle {
                anchors.fill: parent
                color: Qt.rgba(1, 0.55, 0.1, 0.02)
            }

            Rectangle {
                anchors { right: parent.right; top: parent.top; bottom: parent.bottom }
                width: 1
                color: Qt.rgba(1, 0.55, 0.1, 0.08)
            }

            // Logo
            Item {
                anchors { top: parent.top; topMargin: Math.round(20 * s); left: parent.left; right: parent.right }
                height: Math.round(60 * s)

                Rectangle {
                    anchors { left: parent.left; leftMargin: Math.round(20 * s); verticalCenter: parent.verticalCenter }
                    width: Math.round(32 * s); height: width; radius: Math.round(8 * s)
                    color: Qt.rgba(1, 0.55, 0.1, 0.12)
                    border.width: 1
                    border.color: Qt.rgba(1, 0.55, 0.1, 0.15)
                    Text {
                        anchors.centerIn: parent
                        text: "J"
                        color: "#ff8c1a"
                        font { pixelSize: Math.round(16 * s); bold: true; family: "Segoe UI" }
                    }
                }

                Text {
                    anchors { left: parent.left; leftMargin: Math.round(64 * s); top: parent.top; topMargin: Math.round(2 * s) }
                    text: "JARVIS"
                    color: "#e8d5c4"
                    font { pixelSize: Math.round(16 * s); bold: true; letterSpacing: 3; family: "Segoe UI" }
                    opacity: 0.9
                }
                Text {
                    anchors { left: parent.left; leftMargin: Math.round(64 * s); top: parent.top; topMargin: Math.round(24 * s) }
                    text: "AI ASSISTANT"
                    color: "#9a8a7d"
                    font { pixelSize: Math.round(8 * s); letterSpacing: 4; family: "Segoe UI" }
                    opacity: 0.6
                }
            }

            Rectangle {
                anchors { left: parent.left; leftMargin: Math.round(20 * s); right: parent.right; rightMargin: Math.round(20 * s); top: parent.top; topMargin: Math.round(90 * s) }
                height: 1
                color: Qt.rgba(1, 0.55, 0.1, 0.06)
            }

            // Navigation
            Column {
                anchors { top: parent.top; topMargin: Math.round(104 * s); left: parent.left; right: parent.right }
                spacing: Math.round(4 * s)

                component NavItem: Rectangle {
                    property string itemIcon: "\u25C9"
                    property string itemLabel: "Label"
                    property string itemSection: "section"
                    property bool itemActive: false

                    anchors { left: parent.left; leftMargin: Math.round(12 * s); right: parent.right; rightMargin: Math.round(12 * s) }
                    height: Math.round(40 * s)
                    radius: Math.round(8 * s)
                    color: mouseNav.containsMouse || itemActive ? Qt.rgba(1, 0.55, 0.1, 0.08) : "transparent"
                    Behavior on color { ColorAnimation { duration: 150 } }

                    Rectangle {
                        anchors { left: parent.left; top: parent.top; bottom: parent.bottom }
                        width: 3
                        radius: 1.5
                        color: "#ff8c1a"
                        opacity: itemActive ? 0.8 : 0.0
                        Behavior on opacity { NumberAnimation { duration: 200 } }

                        Rectangle {
                            anchors.centerIn: parent
                            width: parent.width * 5
                            height: parent.height * 1.5
                            radius: width / 2
                            color: "transparent"
                            border.width: 1
                            border.color: Qt.rgba(1, 0.55, 0.1, 0.08)
                            opacity: itemActive ? 0.5 : 0.0
                            Behavior on opacity { NumberAnimation { duration: 200 } }
                        }
                    }

                    Row {
                        anchors { left: parent.left; leftMargin: Math.round(16 * s); verticalCenter: parent.verticalCenter }
                        spacing: Math.round(12 * s)
                        Text {
                            anchors.verticalCenter: parent.verticalCenter
                            text: itemIcon
                            color: itemActive ? "#ff8c1a" : (mouseNav.containsMouse ? "#cc9966" : "#665544")
                            font { pixelSize: Math.round(14 * s); family: "Segoe UI" }
                            opacity: itemActive ? 1.0 : 0.6
                            Behavior on color { ColorAnimation { duration: 150 } }
                        }
                        Text {
                            anchors.verticalCenter: parent.verticalCenter
                            text: itemLabel
                            color: itemActive ? "#e8d5c4" : (mouseNav.containsMouse ? "#aa9988" : "#776655")
                            font { pixelSize: Math.round(12 * s); letterSpacing: 1; family: "Segoe UI" }
                            Behavior on color { ColorAnimation { duration: 150 } }
                        }
                    }

                    MouseArea {
                        id: mouseNav
                        anchors.fill: parent; hoverEnabled: true
                        onClicked: {
                            if (typeof bridge !== "undefined" && bridge) bridge.set_sidebar_section(itemSection)
                        }
                    }
                }

                NavItem { itemIcon: "\u25C9"; itemLabel: "Conversation"; itemSection: "conversation"; itemActive: true }
                NavItem { itemIcon: "\u25A6"; itemLabel: "Memory"; itemSection: "memory" }
                NavItem { itemIcon: "\u2699"; itemLabel: "Automation"; itemSection: "automation" }
                NavItem { itemIcon: "\u25C8"; itemLabel: "Files"; itemSection: "files" }
                NavItem { itemIcon: "\u26A1"; itemLabel: "Settings"; itemSection: "settings" }
            }

            // Bottom status
            Column {
                anchors { bottom: parent.bottom; bottomMargin: Math.round(16 * s); left: parent.left; leftMargin: Math.round(20 * s) }
                spacing: Math.round(4 * s)
                Text {
                    text: "Status"
                    color: "#665544"
                    font { pixelSize: Math.round(8 * s); letterSpacing: 2; family: "Segoe UI" }
                }
                Row {
                    spacing: Math.round(12 * s)
                    Repeater {
                        model: [
                            { label: "Net", active: root.internetOk, color: "#00ff88" },
                            { label: "Mic", active: root.micOk, color: "#33aaff" },
                            { label: "Spk", active: root.speakerOk, color: "#ff8c1a" }
                        ]
                        Row {
                            spacing: Math.round(4 * s)
                            Rectangle {
                                width: Math.round(5 * s); height: width; radius: width / 2
                                anchors.verticalCenter: parent.verticalCenter
                                color: modelData.active ? modelData.color : "#333"
                                Behavior on color { ColorAnimation { duration: 300 } }
                            }
                            Text {
                                text: modelData.label
                                color: "#776655"
                                font { pixelSize: Math.round(8 * s); family: "Consolas" }
                            }
                        }
                    }
                }
            }
        }

        // ── CENTER AREA ──────────────────────────────────────────────
        Item {
            anchors { left: leftSidebar.right; right: rightPanel.left; top: parent.top; bottom: parent.bottom }

            ParticleField {
                id: particleField
                anchors.fill: parent
                currentMode: root.currentMode
                voiceEnergy: root.currentMode === "speaking" ? root.assistantLevel : root.micLevel
                z: 0
            }

            AiCore {
                id: mainCore
                width: coreSize
                height: width
                anchors.horizontalCenter: parent.horizontalCenter
                anchors.verticalCenter: parent.verticalCenter
                anchors.verticalCenterOffset: -Math.round(20 * s)
                currentMode: root.currentMode
                amberDominant: false
                z: 1
            }

            Text {
                text: {
                    switch (root.currentMode) {
                        case "listening": return "LISTENING"
                        case "thinking": return "THINKING"
                        case "speaking": return "SPEAKING"
                        default: return ""
                    }
                }
                color: root.currentMode === "listening" ? "#33aaff" : "#ff8c1a"
                font { pixelSize: Math.round(10 * s); bold: true; letterSpacing: 4; family: "Segoe UI" }
                anchors.horizontalCenter: parent.horizontalCenter
                anchors.top: mainCore.bottom
                anchors.topMargin: Math.round(12 * s)
                opacity: root.currentMode !== "idle" ? 1.0 : 0.0
                Behavior on opacity { NumberAnimation { duration: 400 } }
                Behavior on color { ColorAnimation { duration: 400 } }
                z: 2
            }

            VoiceWaveform {
                id: centerWaveform
                width: Math.min(400 * s, parent.width * 0.35)
                height: Math.round(60 * s)
                anchors.horizontalCenter: parent.horizontalCenter
                anchors.top: mainCore.bottom
                anchors.topMargin: Math.round(36 * s)
                currentMode: root.currentMode
                micEnergy: root.micLevel
                assistantEnergy: root.assistantLevel
                opacity: (root.currentMode === "listening" || root.currentMode === "speaking") ? 1.0 : 0.0
                Behavior on opacity { NumberAnimation { duration: 500 } }
                z: 2
            }

            Rectangle {
                id: subtitleBox
                width: Math.min(500 * s, parent.width * 0.35)
                height: Math.round(40 * s)
                anchors.horizontalCenter: parent.horizontalCenter
                anchors.top: centerWaveform.bottom
                anchors.topMargin: Math.round(16 * s)
                radius: Math.round(8 * s)
                color: Qt.rgba(0.02, 0.024, 0.027, 0.7)
                border.width: 1
                border.color: Qt.rgba(1, 0.55, 0.1, 0.12)
                opacity: (root.currentMode !== "idle" && root.subtitleText.length > 0) ? 1.0 : 0.0
                Behavior on opacity { NumberAnimation { duration: 500 } }
                z: 2

                Text {
                    text: root.subtitleText
                    color: "#e0c4a6"
                    font.pixelSize: Math.round(11 * s)
                    font.family: "Segoe UI"
                    wrapMode: Text.WordWrap
                    horizontalAlignment: Text.AlignHCenter
                    anchors.centerIn: parent
                    width: parent.width - Math.round(20 * s)
                    elide: Text.ElideRight
                }
            }
        }

        // ── RIGHT PANEL ──────────────────────────────────────────────
        Rectangle {
            id: rightPanel
            anchors { right: parent.right; top: parent.top; bottom: parent.bottom }
            width: Math.max(rightPanelW, rightPanelMinW)
            color: Qt.rgba(8, 6, 5, 0.88)

            Rectangle {
                anchors { left: parent.left; top: parent.top; bottom: parent.bottom }
                width: 1
                color: Qt.rgba(1, 0.55, 0.1, 0.08)
            }

            Rectangle {
                anchors.fill: parent
                color: Qt.rgba(1, 0.55, 0.1, 0.02)
            }

            // Brand
            Text {
                anchors { top: parent.top; topMargin: Math.round(18 * s); left: parent.left; leftMargin: Math.round(18 * s) }
                text: "JARVIS"
                color: Qt.rgba(1, 0.55, 0.1, 0.35)
                font { pixelSize: Math.round(18 * s); bold: true; letterSpacing: 3; family: "Segoe UI" }
                opacity: 0.5
            }
            Text {
                anchors { top: parent.top; topMargin: Math.round(42 * s); left: parent.left; leftMargin: Math.round(20 * s) }
                text: "AI ASSISTANT"
                color: Qt.rgba(1, 0.55, 0.1, 0.25)
                font { pixelSize: Math.round(9 * s); letterSpacing: 4; family: "Segoe UI" }
                opacity: 0.4
            }

            Rectangle {
                anchors { left: parent.left; leftMargin: Math.round(18 * s); right: parent.right; rightMargin: Math.round(18 * s); top: parent.top; topMargin: Math.round(70 * s) }
                height: 1
                color: Qt.rgba(1, 0.55, 0.1, 0.05)
            }

            // ── Core State ───────────────────────────────────────────
            Text {
                anchors { top: parent.top; topMargin: Math.round(84 * s); left: parent.left; leftMargin: Math.round(18 * s) }
                text: "CORE STATE"
                color: "#776655"
                font { pixelSize: Math.round(7 * s); letterSpacing: 3; family: "Segoe UI" }
            }

            Rectangle {
                anchors { top: parent.top; topMargin: Math.round(100 * s); left: parent.left; leftMargin: Math.round(16 * s); right: parent.right; rightMargin: Math.round(16 * s) }
                height: Math.round(52 * s)
                radius: Math.round(8 * s)
                color: Qt.rgba(255, 255, 255, 0.03)
                border.width: 1
                border.color: Qt.rgba(1, 0.55, 0.1, 0.1)

                Rectangle {
                    anchors.fill: parent
                    radius: parent.radius
                    color: "transparent"
                    border.width: 1
                    border.color: Qt.rgba(1, 0.55, 0.1, 0.04)
                    opacity: 0.5
                }

                Row {
                    anchors { left: parent.left; leftMargin: Math.round(12 * s); verticalCenter: parent.verticalCenter }
                    spacing: Math.round(10 * s)

                    Rectangle {
                        width: Math.round(8 * s); height: width; radius: width / 2
                        anchors.verticalCenter: parent.verticalCenter
                        color: root.currentMode === "idle" ? "#666" :
                               root.currentMode === "listening" ? "#33aaff" :
                               root.currentMode === "thinking" ? "#ffd700" :
                               root.currentMode === "speaking" ? "#ff8c1a" : "#666"
                        Behavior on color { ColorAnimation { duration: 300 } }
                        Rectangle {
                            anchors.centerIn: parent
                            width: parent.width * 2.5
                            height: width
                            radius: width / 2
                            color: parent.color
                            opacity: 0.2
                        }
                    }

                    Column {
                        anchors.verticalCenter: parent.verticalCenter
                        spacing: Math.round(2 * s)
                        Text {
                            text: root.currentMode.charAt(0).toUpperCase() + root.currentMode.slice(1)
                            color: "#e0d5ca"
                            font { pixelSize: Math.round(11 * s); bold: true; family: "Segoe UI" }
                        }
                        Text {
                            text: root.modelName
                            color: "#887766"
                            font { pixelSize: Math.round(8 * s); family: "Consolas" }
                        }
                    }
                }

                Rectangle {
                    anchors { right: parent.right; rightMargin: Math.round(8 * s); verticalCenter: parent.verticalCenter }
                    height: Math.round(20 * s); width: Math.round(60 * s)
                    radius: Math.round(4 * s)
                    color: Qt.rgba(1, 0.55, 0.1, 0.06)
                    border.width: 1
                    border.color: Qt.rgba(1, 0.55, 0.1, 0.08)
                    Text {
                        anchors.centerIn: parent
                        text: root.provider
                        color: "#aa8866"
                        font { pixelSize: Math.round(7 * s); family: "Consolas" }
                        elide: Text.ElideRight
                    }
                }
            }

            // ── Quick Status ─────────────────────────────────────────
            Text {
                anchors { top: parent.top; topMargin: Math.round(168 * s); left: parent.left; leftMargin: Math.round(18 * s) }
                text: "QUICK STATUS"
                color: "#776655"
                font { pixelSize: Math.round(7 * s); letterSpacing: 3; family: "Segoe UI" }
            }

            Column {
                anchors { top: parent.top; topMargin: Math.round(184 * s); left: parent.left; leftMargin: Math.round(16 * s); right: parent.right; rightMargin: Math.round(16 * s) }
                spacing: Math.round(6 * s)

                component StatusCard: Rectangle {
                    property string cardLabel: ""
                    property string cardValue: "--"
                    property color cardAccent: "#ff8c1a"
                    property real cardProgress: 0.0

                    height: Math.round(40 * s)
                    radius: Math.round(6 * s)
                    color: Qt.rgba(255, 255, 255, 0.02)
                    border.width: 1
                    border.color: Qt.rgba(1, 0.55, 0.1, 0.06)

                    Rectangle {
                        anchors.fill: parent
                        radius: parent.radius
                        color: "transparent"
                        border.width: 1
                        border.color: Qt.rgba(1, 1, 1, 0.02)
                        opacity: 0.4
                    }

                    Rectangle {
                        anchors { left: parent.left; top: parent.top; bottom: parent.bottom }
                        width: 2
                        radius: 1
                        color: cardAccent
                        opacity: 0.4
                    }

                    Text {
                        anchors { left: parent.left; leftMargin: Math.round(10 * s); top: parent.top; topMargin: Math.round(4 * s) }
                        text: cardLabel
                        color: "#887766"
                        font { pixelSize: Math.round(7 * s); letterSpacing: 1; family: "Segoe UI" }
                    }
                    Text {
                        anchors { left: parent.left; leftMargin: Math.round(10 * s); bottom: parent.bottom; bottomMargin: Math.round(4 * s) }
                        text: cardValue
                        color: "#e0d5ca"
                        font { pixelSize: Math.round(10 * s); weight: Font.DemiBold; family: "Consolas" }
                    }

                    Rectangle {
                        anchors { right: parent.right; rightMargin: Math.round(10 * s); verticalCenter: parent.verticalCenter }
                        width: Math.round(40 * s); height: Math.round(3 * s)
                        radius: Math.round(1.5 * s)
                        color: Qt.rgba(255, 255, 255, 0.05)
                        Rectangle {
                            height: parent.height; radius: parent.radius
                            anchors { left: parent.left; verticalCenter: parent.verticalCenter }
                            width: parent.width * Math.min(1.0, cardProgress / 100)
                            color: cardAccent
                            opacity: 0.6
                        }
                    }
                }

                StatusCard {
                    id: cpuCard
                    cardLabel: "CPU"
                    cardAccent: "#33aaff"
                    cardValue: root.cpu.toFixed(0) + "%"
                    cardProgress: root.cpu
                }
                StatusCard {
                    id: ramCard
                    cardLabel: "RAM"
                    cardAccent: "#00ff88"
                    cardValue: root.ram.toFixed(0) + "%"
                    cardProgress: root.ram
                }
                StatusCard {
                    id: gpuCard
                    cardLabel: "GPU"
                    cardAccent: "#ffd700"
                    cardValue: root.gpu.toFixed(0) + "%"
                    cardProgress: root.gpu
                }
            }

            // Active Task
            Rectangle {
                anchors { bottom: parent.bottom; bottomMargin: Math.round(16 * s); left: parent.left; leftMargin: Math.round(16 * s); right: parent.right; rightMargin: Math.round(16 * s) }
                height: root.activeTask.length > 0 ? Math.round(40 * s) : 0
                radius: Math.round(6 * s)
                color: Qt.rgba(1, 0.55, 0.1, 0.05)
                border.width: 1
                border.color: Qt.rgba(1, 0.55, 0.1, 0.08)
                visible: root.activeTask.length > 0
                Behavior on height { NumberAnimation { duration: 300 } }

                Column {
                    anchors { left: parent.left; leftMargin: Math.round(10 * s); verticalCenter: parent.verticalCenter }
                    spacing: Math.round(2 * s)
                    Text {
                        text: "CURRENT TASK"
                        color: "#665544"
                        font { pixelSize: Math.round(6 * s); letterSpacing: 2; family: "Segoe UI" }
                    }
                    Text {
                        text: root.activeTask
                        color: "#e0c4a6"
                        font { pixelSize: Math.round(9 * s); family: "Consolas" }
                        elide: Text.ElideRight
                        width: parent.parent.width - Math.round(20 * s)
                    }
                }
            }
        }
    }

    // ==================================================================
    // BOTTOM SECTION (Preview dock)
    // ==================================================================
    Rectangle {
        anchors { left: parent.left; right: parent.right; bottom: parent.bottom }
        height: bottomBarH
        color: Qt.rgba(8, 6, 5, 0.92)

        Rectangle {
            anchors { top: parent.top; left: parent.left; right: parent.right }
            height: 1
            color: Qt.rgba(1, 0.55, 0.1, 0.06)
        }

        Row {
            anchors { left: parent.left; leftMargin: Math.round(20 * s); verticalCenter: parent.verticalCenter }
            spacing: Math.round(20 * s)

            component PreviewItem: Rectangle {
                property string previewLabel: ""
                property string previewIcon: "\u25C9"
                property color previewAccent: "#ff8c1a"

                height: bottomPreviewH - Math.round(8 * s)
                width: Math.round(100 * s)
                radius: Math.round(6 * s)
                color: mousePrev.containsMouse ? Qt.rgba(1, 0.55, 0.1, 0.06) : Qt.rgba(255, 255, 255, 0.02)
                border.width: 1
                border.color: mousePrev.containsMouse ? Qt.rgba(1, 0.55, 0.1, 0.15) : Qt.rgba(255, 255, 255, 0.04)
                Behavior on color { ColorAnimation { duration: 150 } }
                Behavior on border.color { ColorAnimation { duration: 150 } }

                Rectangle {
                    anchors.fill: parent
                    radius: parent.radius
                    color: "transparent"
                    border.width: 1
                    border.color: Qt.rgba(previewAccent.r, previewAccent.g, previewAccent.b, 0.06)
                    opacity: mousePrev.containsMouse ? 0.6 : 0.0
                    Behavior on opacity { NumberAnimation { duration: 150 } }
                }

                Column {
                    anchors.centerIn: parent
                    spacing: Math.round(4 * s)
                    Text {
                        anchors.horizontalCenter: parent.horizontalCenter
                        text: previewIcon
                        color: previewAccent
                        font.pixelSize: Math.round(16 * s)
                        opacity: 0.5
                    }
                    Text {
                        anchors.horizontalCenter: parent.horizontalCenter
                        text: previewLabel
                        color: "#887766"
                        font { pixelSize: Math.round(7 * s); letterSpacing: 1; family: "Segoe UI" }
                    }
                }

                MouseArea {
                    id: mousePrev
                    anchors.fill: parent; hoverEnabled: true
                }
            }

            PreviewItem { previewLabel: "ALWAYS ACCESSIBLE"; previewIcon: "\u25C9"; previewAccent: "#ff8c1a" }
            PreviewItem { previewLabel: "CHROME"; previewIcon: "\u25C8"; previewAccent: "#33aaff" }
            PreviewItem { previewLabel: "VS CODE"; previewIcon: "\u25A3"; previewAccent: "#00ff88" }
            PreviewItem { previewLabel: "FLOATING ORB"; previewIcon: "\u25CE"; previewAccent: "#ffd700" }
            PreviewItem { previewLabel: "TASKBAR"; previewIcon: "\u25AC"; previewAccent: "#ff8c1a" }
        }

        Item {
            anchors { right: parent.right; rightMargin: Math.round(20 * s); verticalCenter: parent.verticalCenter }
            width: Math.round(160 * s)
            height: bottomPreviewH - Math.round(8 * s)

            VoiceWaveform {
                id: miniWaveform
                anchors.fill: parent
                currentMode: root.currentMode
                micEnergy: root.micLevel
                assistantEnergy: root.assistantLevel
                opacity: (root.currentMode === "listening" || root.currentMode === "speaking") ? 0.7 : 0.2
                Behavior on opacity { NumberAnimation { duration: 500 } }
            }
            Text {
                anchors { bottom: parent.bottom; horizontalCenter: parent.horizontalCenter }
                text: "VOICE"
                color: "#665544"
                font { pixelSize: Math.round(6 * s); letterSpacing: 2; family: "Segoe UI" }
            }
        }
    }

    // ==================================================================
    // SECONDARY WINDOWS
    // ==================================================================
    FloatingOrb {
        id: orbWindow
        visible: false
    }

    EdgeDock {
        id: dockWindow
        dockEdge: "left"
        visible: false
    }

    Shortcut {
        sequence: "Escape"
        onActivated: root.requestWindowMode("floating_orb")
    }
}