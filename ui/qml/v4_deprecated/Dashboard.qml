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
            var grad = ctx.createRadialGradient(w/2, h/2, 0, w/2, h/2, w*0.8)
            grad.addColorStop(0, "#0b0805")
            grad.addColorStop(0.5, "#030506")
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
            var grad = ctx.createRadialGradient(w/2, h/2, 0, w/2, h/2, w*0.6)
            if (isListening) {
                grad.addColorStop(0, Qt.rgba(0, 0.1, 0.2, 0.3 * root.glowIntensity))
                grad.addColorStop(0.5, Qt.rgba(0, 0.05, 0.1, 0.1 * root.glowIntensity))
            } else {
                grad.addColorStop(0, Qt.rgba(0.29, 0.13, 0, 0.3 * root.glowIntensity))
                grad.addColorStop(0.4, Qt.rgba(0.09, 0.04, 0, 0.1 * root.glowIntensity))
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
            activeSection: root.sidebarSection
            internetOk: root.internetOk
            micOk: root.micOk
            speakerOk: root.speakerOk
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
            anchors.left: sidebar.right
            anchors.right: rightPanel.left
            anchors.top: parent.top
            anchors.bottom: parent.bottom
            clip: true

            // ── AI Core ──
            AiCore {
                id: aiCore
                anchors.centerIn: parent
                anchors.verticalCenterOffset: -20
                coreMode: root.coreMode
                glowIntensity: root.glowIntensity
                coreColor: root.coreColor
                micEnergy: root.micEnergy
                assistantEnergy: root.assistantEnergy
                z: 1
            }

            // ── Mode Label ──
            Text {
                anchors.top: aiCore.bottom
                anchors.topMargin: 20
                anchors.horizontalCenter: parent.horizontalCenter
                text: root.coreMode.toUpperCase()
                font.family: "Segoe UI"
                font.pixelSize: 10
                font.bold: true
                font.letterSpacing: 4
                color: root.coreColor
                opacity: 0.8
                Behavior on color { ColorAnimation { duration: 400; easing.type: Easing.OutCubic } }
                Behavior on opacity { NumberAnimation { duration: 400 } }
            }

            // ── Voice Waveform ──
            VoicePanel {
                id: voicePanel
                anchors.top: aiCore.bottom
                anchors.topMargin: 50
                anchors.horizontalCenter: parent.horizontalCenter
                coreMode: root.coreMode
                micEnergy: root.micEnergy
                assistantEnergy: root.assistantEnergy
                z: 2
            }

            // ── Subtitle / Conversation Panel ──
            Conversation {
                id: conversation
                anchors.top: voicePanel.bottom
                anchors.topMargin: 15
                anchors.horizontalCenter: parent.horizontalCenter
                subtitleText: root.subtitleText
                coreMode: root.coreMode
                z: 2
            }
        }

        // ── Right Panel ──
        RightPanel {
            id: rightPanel
            anchors.right: parent.right
            anchors.top: parent.top
            anchors.bottom: parent.bottom
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
    }

    // ── Repaint glow canvas when mode changes ──
    onCoreModeChanged: { glowCanvas.requestPaint() }
    onGlowIntensityChanged: { glowCanvas.requestPaint() }

    // ── Initial state sync ──
    Component.onCompleted: {
        try {
            root.coreMode = bridge.coreState || "idle"
        } catch(e) {}
    }
}