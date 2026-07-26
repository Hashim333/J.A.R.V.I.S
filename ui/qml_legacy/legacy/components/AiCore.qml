import QtQuick 2.15

Item {
    id: coreRoot

    property string currentMode: "idle"
    onCurrentModeChanged: { _applyMode(); _handleBurst() }

    property bool amberDominant: false
    property real _pulse: 1.0
    property real _glow: 0.45
    property color _coreColor: "#ff8c1a"
    property real _rotation: 0.0
    property real _listeningRotation: 0.0
    property real _breathScale: 1.0

    property var _colors: {
        "idle":        { core: "#ff8c1a", speed: 0.3, glowTarget: 0.45, pulseMin: 1.0, pulseMax: 1.045, pulseDur: 3200 },
        "listening":   { core: "#33aaff", speed: 1.8, glowTarget: 0.65, pulseMin: 1.0, pulseMax: 1.18,  pulseDur: 500  },
        "thinking":    { core: "#ffd700", speed: 3.0, glowTarget: 0.55, pulseMin: 1.0, pulseMax: 1.08,  pulseDur: 350  },
        "speaking":    { core: "#ff8c1a", speed: 2.0, glowTarget: 0.60, pulseMin: 1.0, pulseMax: 1.12,  pulseDur: 400  },
        "error":       { core: "#ff3355", speed: 0.5, glowTarget: 0.70, pulseMin: 1.0, pulseMax: 1.25,  pulseDur: 300  },
        "offline":     { core: "#444444", speed: 0.1, glowTarget: 0.15, pulseMin: 0.98, pulseMax: 1.0,   pulseDur: 4000 }
    }

    NumberAnimation on _rotation {
        id: mainSpin
        from: 0; to: 360; duration: 12000
        loops: Animation.Infinite; running: true
    }

    NumberAnimation on _listeningRotation {
        id: listeningSpin
        from: 0; to: 360; duration: 3500
        loops: Animation.Infinite; running: false
    }

    NumberAnimation on _breathScale {
        id: breathAnim
        from: 1.0; to: 1.045; duration: 3200
        easing.type: Easing.InOutSine; loops: Animation.Infinite
        running: false
    }

    SequentialAnimation {
        id: fastPulse; loops: Animation.Infinite; running: false
        NumberAnimation { target: coreRoot; property: "_pulse"; from: 1.0; to: 1.18; duration: 500; easing.type: Easing.OutCubic }
        NumberAnimation { target: coreRoot; property: "_pulse"; from: 1.18; to: 1.0; duration: 400; easing.type: Easing.InCubic }
        PauseAnimation { duration: 300 }
    }

    NumberAnimation on _glow {
        id: glowAnim
        from: 0.35; to: 0.55; duration: 2400
        easing.type: Easing.InOutSine; loops: Animation.Infinite
    }

    Behavior on _coreColor { ColorAnimation { duration: 500; easing.type: Easing.OutCubic } }
    Behavior on scale { NumberAnimation { duration: 400; easing.type: Easing.OutCubic } }

    function _applyMode() {
        breathAnim.running = false
        fastPulse.running = false
        listeningSpin.running = false
        glowAnim.stop()

        var cfg = _colors[currentMode] || _colors["idle"]
        _coreColor = cfg.core
        mainSpin.duration = cfg.speed > 0.5 ? 12000 / cfg.speed : 40000
        glowAnim.from = cfg.glowTarget - 0.1
        glowAnim.to = cfg.glowTarget + 0.1
        glowAnim.restart()

        switch (currentMode) {
            case "idle":
                breathAnim.from = cfg.pulseMin
                breathAnim.to = cfg.pulseMax
                breathAnim.duration = cfg.pulseDur
                breathAnim.running = true
                break
            case "listening":
                listeningSpin.running = true
                fastPulse.running = true
                break
            case "thinking":
                breathAnim.from = 1.0
                breathAnim.to = 1.08
                breathAnim.duration = 350
                breathAnim.running = true
                break
            case "speaking":
                breathAnim.from = 1.0
                breathAnim.to = 1.12
                breathAnim.duration = 400
                breathAnim.running = true
                break
            case "error":
                fastPulse.running = true
                break
        }
        _pulse = 1.0
    }

    function _handleBurst() {
        if (currentMode === "listening" || currentMode === "speaking") {
            burstAnim.running = true
        } else {
            burstAnim.running = false
            energyBurst.opacity = 0.0
        }
    }

    readonly property real _currentBreath: {
        var mode = currentMode
        if (mode === "idle" || mode === "thinking" || mode === "speaking")
            return breathAnim.running ? (breathAnim.from + breathAnim.to) / 2 + (breathAnim.to - breathAnim.from) / 2 * Math.sin(Date.now() / breathAnim.duration * Math.PI * 2) : 1.0
        return _pulse
    }

    // ==================================================================
    // AI CORE — 15 LAYERS (per UI_SPECIFICATION.md)
    // ==================================================================

    // ── Layer 0: Outermost ambient corona (2.4x parent) ─────────────
    Rectangle {
        anchors.centerIn: parent
        width: parent.width * 2.4
        height: width
        radius: width / 2
        color: "transparent"
        opacity: coreRoot._glow * 0.15
        Rectangle {
            anchors.fill: parent
            radius: width / 2
            gradient: Gradient {
                GradientStop { position: 0.0; color: Qt.rgba(coreRoot._coreColor.r, coreRoot._coreColor.g, coreRoot._coreColor.b, 0.15) }
                GradientStop { position: 0.25; color: Qt.rgba(coreRoot._coreColor.r, coreRoot._coreColor.g, coreRoot._coreColor.b, 0.04) }
                GradientStop { position: 1.0; color: "transparent" }
            }
        }
    }

    // ── Layer 1: Outer glow ring (1.6x parent) ─────────────────────
    Rectangle {
        anchors.centerIn: parent
        width: parent.width * 1.6
        height: width
        radius: width / 2
        gradient: Gradient {
            GradientStop { position: 0.0; color: Qt.rgba(coreRoot._coreColor.r, coreRoot._coreColor.g, coreRoot._coreColor.b, 0.30) }
            GradientStop { position: 0.35; color: Qt.rgba(coreRoot._coreColor.r, coreRoot._coreColor.g, coreRoot._coreColor.b, 0.06) }
            GradientStop { position: 1.0; color: "transparent" }
        }
        opacity: coreRoot._glow * 0.5
    }

    // ── Layer 2: Mid glow ring (1.1x parent) ───────────────────────
    Rectangle {
        anchors.centerIn: parent
        width: parent.width * 1.1
        height: width
        radius: width / 2
        gradient: Gradient {
            GradientStop { position: 0.0; color: Qt.rgba(coreRoot._coreColor.r, coreRoot._coreColor.g, coreRoot._coreColor.b, 0.50) }
            GradientStop { position: 0.40; color: Qt.rgba(coreRoot._coreColor.r, coreRoot._coreColor.g, coreRoot._coreColor.b, 0.08) }
            GradientStop { position: 1.0; color: "transparent" }
        }
        opacity: coreRoot._glow * 0.6
    }

    // ── Layer 3: Ring 1 — Outer orbit ring (0.85x, 1.2px) ──────────
    Rectangle {
        anchors.centerIn: parent
        width: parent.width * 0.85
        height: width
        radius: width / 2
        color: "transparent"
        border.width: 1.2
        border.color: Qt.rgba(coreRoot._coreColor.r, coreRoot._coreColor.g, coreRoot._coreColor.b, 0.20 * coreRoot._glow)
        opacity: 0.7
        rotation: coreRoot._rotation

        Rectangle {
            anchors.centerIn: parent
            width: parent.width * 0.85 + 4
            height: width
            radius: width / 2
            color: "transparent"
            border.width: 3
            border.color: Qt.rgba(coreRoot._coreColor.r, coreRoot._coreColor.g, coreRoot._coreColor.b, 0.06 * coreRoot._glow)
            opacity: 0.8
        }
    }

    // ── Layer 4: Ring 2 — Inner orbit ring (0.65x, 0.8px, CCW) ────
    Rectangle {
        anchors.centerIn: parent
        width: parent.width * 0.65
        height: width
        radius: width / 2
        color: "transparent"
        border.width: 0.8
        border.color: Qt.rgba(coreRoot._coreColor.r, coreRoot._coreColor.g, coreRoot._coreColor.b, 0.25 * coreRoot._glow)
        opacity: 0.55
        rotation: -coreRoot._rotation * 1.3
    }

    // ── Layer 5: Ring 3 — Listening mode ring (0.75x, 0.6px, blue) ─
    Rectangle {
        anchors.centerIn: parent
        width: parent.width * 0.75
        height: width
        radius: width / 2
        color: "transparent"
        border.width: 0.6
        border.color: Qt.rgba(0.2, 0.67, 1.0, 0.15 * coreRoot._glow)
        opacity: currentMode === "listening" ? 0.8 : 0.0
        Behavior on opacity { NumberAnimation { duration: 500 } }
        rotation: coreRoot._listeningRotation

        Rectangle {
            anchors.centerIn: parent
            width: parent.width * 0.75 + 4
            height: width
            radius: width / 2
            color: "transparent"
            border.width: 2
            border.color: Qt.rgba(0.2, 0.67, 1.0, 0.05)
            opacity: 0.6
        }
    }

    // ── Layer 6: Ring 4 — Innermost ring (0.45x, 1.0px) ────────────
    Rectangle {
        anchors.centerIn: parent
        width: parent.width * 0.45
        height: width
        radius: width / 2
        color: "transparent"
        border.width: 1.0
        border.color: Qt.rgba(coreRoot._coreColor.r, coreRoot._coreColor.g, coreRoot._coreColor.b, 0.35 * coreRoot._glow)
        opacity: 0.75
        rotation: coreRoot._rotation * 0.7

        Rectangle {
            anchors.centerIn: parent
            width: parent.width * 0.45 * 0.82
            height: width
            radius: width / 2
            color: "transparent"
            border.width: 0.4
            border.color: Qt.rgba(coreRoot._coreColor.r, coreRoot._coreColor.g, coreRoot._coreColor.b, 0.12)
            opacity: 0.6
        }
    }

    // ── Layer 7: Hexagonal inner texture (0.48x parent) ────────────
    Canvas {
        id: hexCanvas
        anchors.centerIn: parent
        width: parent.width * 0.48
        height: width
        opacity: 0.12 + 0.08 * coreRoot._glow
        rotation: coreRoot._rotation * 0.3

        onPaint: {
            var ctx = getContext("2d")
            var w = width
            var h = height
            ctx.clearRect(0, 0, w, h)

            var hexRadius = w * 0.045
            var rows = Math.floor(h / (hexRadius * 1.75)) + 1
            var cols = Math.floor(w / (hexRadius * 1.5)) + 1
            var startX = (w - (cols - 1) * hexRadius * 1.5) / 2

            ctx.shadowColor = Qt.rgba(coreRoot._coreColor.r, coreRoot._coreColor.g, coreRoot._coreColor.b, 0.3)
            ctx.shadowBlur = 2
            ctx.strokeStyle = Qt.rgba(coreRoot._coreColor.r, coreRoot._coreColor.g, coreRoot._coreColor.b, 0.5)
            ctx.lineWidth = 0.5

            for (var row = 0; row < rows; row++) {
                var offsetX = row % 2 === 0 ? 0 : hexRadius * 0.75
                for (var col = 0; col < cols; col++) {
                    var hx = startX + col * hexRadius * 1.5 + offsetX
                    var hy = row * hexRadius * 1.75 + hexRadius
                    if (hx < -hexRadius || hx > w + hexRadius || hy < -hexRadius || hy > h + hexRadius) continue

                    ctx.beginPath()
                    for (var side = 0; side < 6; side++) {
                        var angle = Math.PI / 3 * side - Math.PI / 6
                        var px = hx + hexRadius * Math.cos(angle)
                        var py = hy + hexRadius * Math.sin(angle)
                        if (side === 0) ctx.moveTo(px, py)
                        else ctx.lineTo(px, py)
                    }
                    ctx.closePath()
                    ctx.stroke()
                }
            }
            ctx.shadowBlur = 0
        }
    }

    // ── Layer 8: Inner glow sphere (0.32x parent) ───────────────────
    Rectangle {
        anchors.centerIn: parent
        width: parent.width * 0.32
        height: width
        radius: width / 2
        gradient: Gradient {
            GradientStop { position: 0.0; color: Qt.lighter(coreRoot._coreColor, 1.6) }
            GradientStop { position: 0.15; color: coreRoot._coreColor }
            GradientStop { position: 0.45; color: Qt.darker(coreRoot._coreColor, 1.3) }
            GradientStop { position: 0.75; color: Qt.rgba(coreRoot._coreColor.r, coreRoot._coreColor.g, coreRoot._coreColor.b, 0.0) }
            GradientStop { position: 1.0; color: Qt.rgba(16, 5, 0, 1.0) }
        }
        opacity: 0.9 * (0.8 + 0.2 * (_pulse > 0 ? _pulse : 1.0))
    }

    // ── Layer 9: Core hotspot (0.14x parent, white center) ──────────
    Rectangle {
        anchors.centerIn: parent
        width: parent.width * 0.14
        height: width
        radius: width / 2
        gradient: Gradient {
            GradientStop { position: 0.0; color: "#ffffff" }
            GradientStop { position: 0.2; color: Qt.lighter(coreRoot._coreColor, 1.4) }
            GradientStop { position: 0.5; color: Qt.rgba(coreRoot._coreColor.r, coreRoot._coreColor.g, coreRoot._coreColor.b, 0.5) }
            GradientStop { position: 1.0; color: "transparent" }
        }
        opacity: 0.65 * (0.8 + 0.2 * (_pulse > 0 ? _pulse : 1.0))
    }

    // ── Layer 10: Upper-left glare (0.5x parent) ────────────────────
    Rectangle {
        anchors.centerIn: parent
        width: parent.width * 0.5
        height: width
        radius: width / 2
        gradient: Gradient {
            GradientStop { position: 0.0; color: Qt.rgba(1, 0.85, 0.4, 0.35 * coreRoot._glow) }
            GradientStop { position: 0.25; color: Qt.rgba(coreRoot._coreColor.r, coreRoot._coreColor.g, coreRoot._coreColor.b, 0.10) }
            GradientStop { position: 1.0; color: "transparent" }
        }
        opacity: coreRoot._glow * 0.55
    }

    // ── Layer 11: Bottom-right reflection (0.35x parent) ────────────
    Rectangle {
        anchors.centerIn: parent
        width: parent.width * 0.35
        height: width
        radius: width / 2
        gradient: Gradient {
            GradientStop { position: 1.0; color: Qt.rgba(coreRoot._coreColor.r, coreRoot._coreColor.g, coreRoot._coreColor.b, 0.12 * coreRoot._glow) }
            GradientStop { position: 0.4; color: "transparent" }
        }
        opacity: coreRoot._glow * 0.3
    }

    // ── Layer 12: Expanding pulse ring 1 (2200ms expand, 600ms pause) ─
    Rectangle {
        id: pulseRing
        anchors.centerIn: parent
        width: parent.width * 0.35
        height: width
        radius: width / 2
        color: "transparent"
        border.width: 1.0
        border.color: Qt.rgba(coreRoot._coreColor.r, coreRoot._coreColor.g, coreRoot._coreColor.b, coreRoot._glow * 0.35)
        Behavior on border.color { ColorAnimation { duration: 400 } }

        SequentialAnimation on opacity {
            loops: Animation.Infinite
            NumberAnimation { from: 0.4; to: 0.0; duration: 2200; easing.type: Easing.InSine }
            PauseAnimation { duration: 600 }
        }
        SequentialAnimation on width {
            loops: Animation.Infinite
            NumberAnimation { from: parent.width * 0.35; to: parent.width * 1.3; duration: 2200; easing.type: Easing.InSine }
            PauseAnimation { duration: 600 }
        }
        SequentialAnimation on height {
            loops: Animation.Infinite
            NumberAnimation { from: parent.width * 0.35; to: parent.width * 1.3; duration: 2200; easing.type: Easing.InSine }
            PauseAnimation { duration: 600 }
        }
    }

    // ── Layer 13: Expanding pulse ring 2 (1100ms delay, 0.6px border) ─
    Rectangle {
        id: pulseRing2
        anchors.centerIn: parent
        width: parent.width * 0.35
        height: width
        radius: width / 2
        color: "transparent"
        border.width: 0.6
        border.color: Qt.rgba(coreRoot._coreColor.r, coreRoot._coreColor.g, coreRoot._coreColor.b, coreRoot._glow * 0.20)
        Behavior on border.color { ColorAnimation { duration: 400 } }

        SequentialAnimation on opacity {
            loops: Animation.Infinite
            PauseAnimation { duration: 1100 }
            NumberAnimation { from: 0.3; to: 0.0; duration: 2200; easing.type: Easing.InSine }
            PauseAnimation { duration: 600 }
        }
        SequentialAnimation on width {
            loops: Animation.Infinite
            PauseAnimation { duration: 1100 }
            NumberAnimation { from: parent.width * 0.35; to: parent.width * 1.3; duration: 2200; easing.type: Easing.InSine }
            PauseAnimation { duration: 600 }
        }
        SequentialAnimation on height {
            loops: Animation.Infinite
            PauseAnimation { duration: 1100 }
            NumberAnimation { from: parent.width * 0.35; to: parent.width * 1.3; duration: 2200; easing.type: Easing.InSine }
            PauseAnimation { duration: 600 }
        }
    }

    // ── Energy pulse burst (mode-reactive, expand 0.2x→1.5x, 800ms) ──
    Rectangle {
        id: energyBurst
        anchors.centerIn: parent
        width: parent.width * 0.2
        height: width
        radius: width / 2
        color: "transparent"
        border.width: 2
        border.color: Qt.rgba(coreRoot._coreColor.r, coreRoot._coreColor.g, coreRoot._coreColor.b, 0.0)
        opacity: 0.0

        SequentialAnimation {
            id: burstAnim; loops: Animation.Infinite; running: false
            NumberAnimation { target: energyBurst; property: "opacity"; from: 0.6; to: 0.0; duration: 800; easing.type: Easing.OutCubic }
            NumberAnimation { target: energyBurst; property: "width"; from: parent.width * 0.2; to: parent.width * 1.5; duration: 800; easing.type: Easing.OutCubic }
            NumberAnimation { target: energyBurst; property: "height"; from: parent.width * 0.2; to: parent.width * 1.5; duration: 800; easing.type: Easing.OutCubic }
            NumberAnimation { target: energyBurst; property: "border.color"; from: Qt.rgba(coreRoot._coreColor.r, coreRoot._coreColor.g, coreRoot._coreColor.b, 0.8); to: Qt.rgba(coreRoot._coreColor.r, coreRoot._coreColor.g, coreRoot._coreColor.b, 0.0); duration: 800 }
            PauseAnimation { duration: 1200 }
        }
    }

    // ── Layer 14: Orbiting lights — outer set (6) ─────────────────
    Repeater {
        id: outerLightsRepeater
        model: 6

        Item {
            property real baseAngle: (index / 6) * 360
            property real orbitRadius: parent.width * (0.20 + index * 0.07)
            property real dotSize: 2.5 + (index % 3) * 0.8
            property real speed: (0.5 + index * 0.15) * (index % 2 === 0 ? 1 : -1)
            property real pulse: 0.5 + 0.5 * Math.sin(Date.now() / 500 + index)

            Timer {
                interval: 33; running: true; repeat: true
                onTriggered: {
                    var a = baseAngle + coreRoot._rotation * speed
                    var r = orbitRadius
                    parent.x = parent.parent.width / 2 + r * Math.cos(a * Math.PI / 180) - dotSize / 2
                    parent.y = parent.parent.height / 2 + r * Math.sin(a * Math.PI / 180) - dotSize / 2
                    parent.pulse = 0.5 + 0.5 * Math.sin(Date.now() / 500 + index)
                }
            }

            Rectangle {
                x: 0; y: 0
                width: parent.dotSize
                height: width
                radius: width / 2
                color: Qt.lighter(coreRoot._coreColor, 1.4)
                opacity: 0.5 + 0.4 * parent.pulse

                Rectangle {
                    anchors.centerIn: parent
                    width: parent.width * 4
                    height: width
                    radius: width / 2
                    color: "transparent"
                    border.width: 0.5
                    border.color: Qt.rgba(coreRoot._coreColor.r, coreRoot._coreColor.g, coreRoot._coreColor.b, 0.12)
                    opacity: 0.6
                }
            }
        }
    }

    // ── Layer 15: Orbiting lights — inner set (4, faster) ─────────
    Repeater {
        id: innerLightsRepeater
        model: 4

        Item {
            property real baseAngle: (index / 4) * 360 + 45
            property real orbitRadius: parent.width * (0.12 + index * 0.04)
            property real dotSize: 2.0 + index * 0.4
            property real speed: (1.2 + index * 0.3) * (index % 2 === 0 ? -1 : 1)
            property real pulse: 0.5 + 0.5 * Math.sin(Date.now() / 400 + index * 1.5)

            Timer {
                interval: 33; running: true; repeat: true
                onTriggered: {
                    var a = baseAngle + coreRoot._rotation * speed
                    var r = orbitRadius
                    parent.x = parent.parent.width / 2 + r * Math.cos(a * Math.PI / 180) - dotSize / 2
                    parent.y = parent.parent.height / 2 + r * Math.sin(a * Math.PI / 180) - dotSize / 2
                    parent.pulse = 0.5 + 0.5 * Math.sin(Date.now() / 400 + index * 1.5)
                }
            }

            Rectangle {
                x: 0; y: 0
                width: parent.dotSize
                height: width
                radius: width / 2
                color: "#ffffff"
                opacity: 0.6 + 0.3 * parent.pulse
            }
        }
    }

    // ── Bloom overlay (simulated volumetric glow 1.8x parent) ────────
    Rectangle {
        anchors.centerIn: parent
        width: parent.width * 1.8
        height: width
        radius: width / 2
        opacity: coreRoot._glow * 0.08 * (0.8 + 0.2 * coreRoot._breathScale)
        gradient: Gradient {
            GradientStop { position: 0.0; color: Qt.rgba(coreRoot._coreColor.r, coreRoot._coreColor.g, coreRoot._coreColor.b, 0.12) }
            GradientStop { position: 0.5; color: Qt.rgba(coreRoot._coreColor.r, coreRoot._coreColor.g, coreRoot._coreColor.b, 0.02) }
            GradientStop { position: 1.0; color: "transparent" }
        }
        Behavior on opacity { NumberAnimation { duration: 600 } }
    }

    Component.onCompleted: _applyMode()
    onWidthChanged: hexCanvas.requestPaint()
}