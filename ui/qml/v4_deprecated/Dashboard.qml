import QtQuick 2.15

/**
 * Dashboard — main layout orchestrator.
 * Bridge is available as a QML context property (set by app.py).
 * Window controls call functions on the parent Window.
 */
Item {
    id: root

    // ── State properties (synced from bridge context property) ──
    property string coreMode: "idle"
    property real glowIntensity: 0.45
    property color coreColor: "#ff8c1a"
    property real micEnergy: 0.0
    property real assistantEnergy: 0.0
    property string subtitleText: ""
    property bool internetOk: false
    property bool micOk: false
    property bool speakerOk: false
    property string provider: "ElevenLabs"
    property string model: "Qwen 2.5 3B"
    property real cpuUsage: 0
    property real ramUsage: 0
    property real gpuUsage: 0
    property string currentTask: ""
    property string sidebarSection: "conversation"
    readonly property real layoutScale: Math.max(0.74, Math.min(width / 1920, height / 1080))
    readonly property real sideWidth: width < 1500 ? 218 : 266
    readonly property real rightWidth: width < 1500 ? 430 : 590

    anchors.fill: parent

    // ── Pure black background ──
    Rectangle {
        anchors.fill: parent
        color: "#000000"
    }

    // ── Background gradient (radial via Canvas) ──
    Canvas {
        id: bgCanvas
        anchors.fill: parent
        antialiasing: true
        onPaint: {
            var ctx = getContext("2d")
            if (!ctx) return
            var w = width, h = height
            var grad = ctx.createRadialGradient(w*0.45, h*0.38, 0, w*0.45, h*0.38, w*0.75)
            grad.addColorStop(0, "#120804")
            grad.addColorStop(0.45, "#030608")
            grad.addColorStop(1, "#010101")
            ctx.fillStyle = grad
            ctx.fillRect(0, 0, w, h)
        }
    }

    // ── Ambient glow field ──
    Canvas {
        id: glowCanvas
        anchors.fill: parent
        antialiasing: true
        onPaint: {
            var ctx = getContext("2d")
            if (!ctx) return
            var w = width, h = height
            var isListening = root.coreMode === "listening"
            var grad = ctx.createRadialGradient(w*0.45, h*0.38, 0, w*0.45, h*0.38, w*0.55)
            if (isListening) {
                grad.addColorStop(0, Qt.rgba(0, 0.1, 0.2, 0.3 * root.glowIntensity))
                grad.addColorStop(0.5, Qt.rgba(0, 0.05, 0.1, 0.1 * root.glowIntensity))
            } else {
                grad.addColorStop(0, Qt.rgba(0.9, 0.32, 0, 0.28 * root.glowIntensity))
                grad.addColorStop(0.4, Qt.rgba(0.28, 0.08, 0, 0.12 * root.glowIntensity))
            }
            grad.addColorStop(1, "transparent")
            ctx.fillStyle = grad
            ctx.fillRect(0, 0, w, h)
        }
    }

    // ── Particle Background ──
    ParticleBackground {
        id: particles
        anchors.fill: parent
        coreMode: root.coreMode
        micEnergy: root.micEnergy
        assistantEnergy: root.assistantEnergy
        glowIntensity: root.glowIntensity
        coreColor: root.coreColor
        z: 0
    }

    // ── Top accent lines ──
    Rectangle {
        y: 0; width: parent.width; height: 1
        color: "#57320B"; opacity: 0.85; z: 5
    }
    Rectangle {
        y: 1; width: parent.width; height: 1
        color: "#120b04"; z: 5
    }

    // ── Top Bar / Header with window controls ──
    Header {
        id: header
        z: 5
    }

    // ── Main Content Row ──
    Item {
        anchors.top: header.bottom
        anchors.bottom: footer.top
        anchors.left: parent.left
        anchors.right: parent.right

        // ── Left Sidebar ──
        Sidebar {
            id: sidebar
            anchors.left: parent.left
            anchors.top: parent.top
            anchors.bottom: parent.bottom
            width: root.sideWidth
            activeSection: root.sidebarSection
            internetOk: root.internetOk
            micOk: root.micOk
            speakerOk: root.speakerOk
            cpuUsage: root.cpuUsage
            ramUsage: root.ramUsage
            gpuUsage: root.gpuUsage
            z: 3
            onSectionClicked: function(section) {
                root.sidebarSection = section
                if (typeof bridge !== 'undefined' && bridge && bridge.set_sidebar_section) {
                    bridge.set_sidebar_section(section)
                }
            }
        }

        // ── Center Area ──
        Item {
            id: centerArea
            anchors.left: sidebar.right
            anchors.right: rightPanel.left
            anchors.top: parent.top
            anchors.bottom: parent.bottom
            clip: true
            readonly property real coreSize: Math.min(width * 0.82, height * 0.72, root.width < 1500 ? 500 : 760)

            // ── AI Core ──
            AiCore {
                id: aiCore
                anchors.horizontalCenter: parent.horizontalCenter
                anchors.top: parent.top
                anchors.topMargin: Math.max(12, parent.height * 0.025)
                baseSize: centerArea.coreSize
                coreMode: root.coreMode
                glowIntensity: root.glowIntensity
                coreColor: root.coreColor
                micEnergy: root.micEnergy
                assistantEnergy: root.assistantEnergy
                z: 1
            }

            // ── Mode Label ──
            Text {
                id: modeLabel
                anchors.top: aiCore.bottom
                anchors.topMargin: -Math.max(16, centerArea.coreSize * 0.09)
                anchors.horizontalCenter: parent.horizontalCenter
                text: root.coreMode.toUpperCase()
                font.family: "Segoe UI"
                font.pixelSize: root.width < 1500 ? 16 : 24
                font.bold: true
                font.letterSpacing: 1
                color: root.coreColor
                opacity: 0.85
                Behavior on color { ColorAnimation { duration: 400; easing.type: Easing.OutCubic } }
                Behavior on opacity { NumberAnimation { duration: 400 } }
            }

            // ── Subtitle text ──
            Text {
                id: subtitleLine
                anchors.top: modeLabel.bottom
                anchors.topMargin: 10
                anchors.horizontalCenter: parent.horizontalCenter
                text: root.subtitleText || "Yes, sir. I'm listening.\nHow can I help you?"
                font.family: "Segoe UI"
                font.pixelSize: root.width < 1500 ? 14 : 18
                lineHeight: 1.25
                color: "#f1d7bd"
                opacity: 0.92
                horizontalAlignment: Text.AlignHCenter
                wrapMode: Text.WordWrap
                width: Math.min(520, parent.width * 0.74)
                Behavior on opacity { NumberAnimation { duration: 300 } }
            }

            // ── Voice Waveform ──
            VoicePanel {
                id: voicePanel
                anchors.top: subtitleLine.bottom
                anchors.topMargin: 18
                anchors.horizontalCenter: parent.horizontalCenter
                width: Math.min(560, parent.width * 0.70)
                coreMode: root.coreMode
                micEnergy: root.micEnergy
                assistantEnergy: root.assistantEnergy
                z: 2
            }

            // ── Conversation History Panel (fixed-height, bottom-anchored) ──
            Conversation {
                id: conversation
                anchors.bottom: parent.bottom
                anchors.bottomMargin: 16
                anchors.horizontalCenter: parent.horizontalCenter
                width: Math.min(760, parent.width * 0.78)
                height: Math.max(124, Math.min(190, parent.height * 0.19))
                z: 2
            }

        }

        // ── Right Panel ──
            RightPanel {
            id: rightPanel
            anchors.right: parent.right
            anchors.top: parent.top
            anchors.bottom: parent.bottom
            width: root.rightWidth
            coreMode: root.coreMode
            provider: root.provider
            model: root.model
            cpuUsage: root.cpuUsage
            ramUsage: root.ramUsage
            gpuUsage: root.gpuUsage
            currentTask: root.currentTask
            z: 3
        }
    }

    // ── Footer / Bottom Section ──
    Footer {
        id: footer
        anchors.bottom: parent.bottom
        height: root.width < 1500 ? 52 : 64
        micEnergy: root.micEnergy
    }

    // ── Bridge connections (bridge is a context property from app.py) ──
    Connections {
        target: bridge
        ignoreUnknownSignals: true

        function onCoreStateChanged(state) { root.coreMode = state }
        function onMicEnergyChanged(energy) { root.micEnergy = energy }
        function onAssistantEnergyChanged(energy) { root.assistantEnergy = energy }
        function onSubtitleChanged(text) { root.subtitleText = text }
        function onInternetStatusChanged(ok) { root.internetOk = ok }
        function onMicStatusChanged(ok) { root.micOk = ok }
        function onSpeakerStatusChanged(ok) { root.speakerOk = ok }
        function onProviderChanged(name) { root.provider = name }
        function onModelChanged(name) { root.model = name }
        function onCpuUsageChanged(pct) { root.cpuUsage = pct }
        function onRamUsageChanged(pct) { root.ramUsage = pct }
        function onGpuUsageChanged(pct) { root.gpuUsage = pct }
        function onCurrentTaskChanged(task) { root.currentTask = task }
        function onBatteryChanged(pct) { /* not displayed yet */ }
        function onWindowModeChanged(mode) { /* not displayed yet */ }
        function onClockChanged(time) { /* header has its own clock */ }
        function onConversationHistoryChanged() {
            conversation.refresh()
        }
    }

    // ── Repaint glow canvas when mode changes ──
    onCoreModeChanged: { glowCanvas.requestPaint() }
    onGlowIntensityChanged: { glowCanvas.requestPaint() }

    // ── Initial state sync ──
    Component.onCompleted: {
        try {
            root.coreMode = bridge.coreState || "idle"
            conversation.refresh()
        } catch(e) {}
    }
}
