import QtQuick 2.15

Item {
    id: root

    property string coreMode: "idle"
    property real glowIntensity: 0.45
    property color coreColor: "#ff8c1a"
    property real micEnergy: 0.0
    property real assistantEnergy: 0.0

    readonly property real baseSize: 600
    width: baseSize
    height: baseSize

    readonly property color idleColor:    "#ff8c1a"
    readonly property color listenColor:  "#33aaff"
    readonly property color thinkColor:   "#ffd700"
    readonly property color speakColor:   "#ff8c1a"
    readonly property color errorColor:   "#ff3355"
    readonly property color offlineColor: "#444444"

    function modeColor() {
        switch (root.coreMode) {
            case "listening": return listenColor
            case "thinking":  return thinkColor
            case "speaking":  return speakColor
            case "error":     return errorColor
            case "offline":   return offlineColor
            default:          return idleColor
        }
    }

    // Ring speeds in degrees per second for each mode
    readonly property var ringSpeeds: ({
        "idle":      { r1: 140, r2: -240, r3: 90,  r4: -140, r5: 47  },
        "listening": { r1: 70,  r2: -120, r3: 45,  r4: -70,  r5: 24  },
        "thinking":  { r1: 350, r2: -600, r3: 225, r4: -350, r5: 118 },
        "speaking":  { r1: 170, r2: -290, r3: 110, r4: -170, r5: 57  },
        "error":     { r1: 250, r2: -430, r3: 160, r4: -250, r5: 85  },
        "offline":   { r1: 40,  r2: -70,  r3: 25,  r4: -40,  r5: 14  }
    })

    function ringDegPerSec(ring) {
        var speeds = ringSpeeds[root.coreMode] || ringSpeeds["idle"]
        return speeds[ring] || 140
    }

    // Monotonic running time (seconds) for continuous rotation
    property real runningTime: 0
    Timer {
        interval: 16
        running: true
        repeat: true
        onTriggered: root.runningTime += 0.016
    }

    // Breathing oscillation (0→1 loop) for subtle scale/opacity only
    property real breathe: 0
    NumberAnimation on breathe {
        loops: Animation.Infinite
        from: 0; to: 1
        duration: 3200
        easing.type: Easing.InOutSine
    }

    // Glow oscillation (0.35→0.65 loop) for intensity variation
    property real glowOsc: 0
    NumberAnimation on glowOsc {
        loops: Animation.Infinite
        from: 0.35; to: 0.65
        duration: 2400
        easing.type: Easing.InOutSine
    }

    // Pulse progress for expanding rings
    property real pulseProgress: 0
    NumberAnimation on pulseProgress {
        loops: Animation.Infinite
        from: 0; to: 1
        duration: 2800
    }

    // Breathing scale — subtle enough that 0→1 wrap is invisible
    readonly property real breatheScale: 1.0 + 0.045 * (0.5 + 0.5 * Math.sin(breathe * Math.PI * 2))
    transform: Scale {
        origin.x: root.width / 2
        origin.y: root.height / 2
        xScale: breatheScale
        yScale: breatheScale
    }

    // Map coreMode to color
    onCoreModeChanged: {
        root.coreColor = root.modeColor()
    }
    Component.onCompleted: {
        root.coreColor = root.modeColor()
    }

    // ── Layer 0: Outermost Ambient Corona (900px) ──
    Canvas {
        width: 900; height: 900
        x: (parent.width - width) / 2
        y: (parent.height - height) / 2
        opacity: glowIntensity * 0.08
        antialiasing: true
        onPaint: {
            var ctx = getContext("2d")
            if (!ctx) return
            var w = width, h = height, c = root.coreColor
            ctx.clearRect(0, 0, w, h)
            var grad = ctx.createRadialGradient(w/2, h/2, 0, w/2, h/2, w/2)
            grad.addColorStop(0, Qt.rgba(c.r, c.g, c.b, 0.08))
            grad.addColorStop(0.4, Qt.rgba(c.r, c.g, c.b, 0.03))
            grad.addColorStop(1, "transparent")
            ctx.fillStyle = grad
            ctx.fillRect(0, 0, w, h)
        }
        Behavior on opacity { NumberAnimation { duration: 500; easing.type: Easing.OutCubic } }
    }

    // ── Layer 1: Outer Glow Ring (600px) ──
    Canvas {
        width: 600; height: 600
        x: (parent.width - width) / 2
        y: (parent.height - height) / 2
        opacity: glowIntensity * 0.2
        antialiasing: true
        onPaint: {
            var ctx = getContext("2d")
            if (!ctx) return
            var w = width, h = height, c = root.coreColor
            ctx.clearRect(0, 0, w, h)
            var grad = ctx.createRadialGradient(w/2, h/2, 0, w/2, h/2, w/2)
            grad.addColorStop(0, Qt.rgba(c.r, c.g, c.b, 0.2))
            grad.addColorStop(0.3, Qt.rgba(c.r, c.g, c.b, 0.08))
            grad.addColorStop(0.6, Qt.rgba(c.r, c.g, c.b, 0.02))
            grad.addColorStop(1, "transparent")
            ctx.fillStyle = grad
            ctx.fillRect(0, 0, w, h)
        }
        Behavior on opacity { NumberAnimation { duration: 500; easing.type: Easing.OutCubic } }
    }

    // ── Layer 2: Mid Glow Ring (450px) ──
    Canvas {
        width: 450; height: 450
        x: (parent.width - width) / 2
        y: (parent.height - height) / 2
        opacity: glowIntensity * 0.4
        antialiasing: true
        onPaint: {
            var ctx = getContext("2d")
            if (!ctx) return
            var w = width, h = height, c = root.coreColor
            ctx.clearRect(0, 0, w, h)
            var grad = ctx.createRadialGradient(w/2, h/2, 0, w/2, h/2, w/2)
            grad.addColorStop(0, Qt.rgba(c.r, c.g, c.b, 0.4))
            grad.addColorStop(0.3, Qt.rgba(c.r, c.g, c.b, 0.15))
            grad.addColorStop(0.6, Qt.rgba(c.r, c.g, c.b, 0.04))
            grad.addColorStop(1, "transparent")
            ctx.fillStyle = grad
            ctx.fillRect(0, 0, w, h)
        }
        Behavior on opacity { NumberAnimation { duration: 500; easing.type: Easing.OutCubic } }
    }

    // ── Layer 3: Concentric Rotating Ring 1 (outermost, 380px) ──
    Rectangle {
        id: ring1
        width: 380; height: 380
        radius: 190
        x: (parent.width - width) / 2
        y: (parent.height - height) / 2
        border.width: 1.5
        border.color: Qt.rgba(coreColor.r, coreColor.g, coreColor.b, 0.15 * glowIntensity)
        color: "transparent"
        transform: Rotation {
            origin.x: ring1.width / 2
            origin.y: ring1.height / 2
            angle: root.runningTime * root.ringDegPerSec("r1") % 360
        }
        Behavior on border.color { ColorAnimation { duration: 500; easing.type: Easing.OutCubic } }
    }

    // ── Layer 4: Concentric Ring 2 (320px) ──
    Rectangle {
        id: ring2
        width: 320; height: 320
        radius: 160
        x: (parent.width - width) / 2
        y: (parent.height - height) / 2
        border.width: 1.0
        border.color: Qt.rgba(coreColor.r, coreColor.g, coreColor.b, 0.2 * glowIntensity)
        color: "transparent"
        transform: Rotation {
            origin.x: ring2.width / 2
            origin.y: ring2.height / 2
            angle: root.runningTime * root.ringDegPerSec("r2") % 360
        }
        Behavior on border.color { ColorAnimation { duration: 500; easing.type: Easing.OutCubic } }
    }

    // ── Layer 5: Concentric Ring 3 (270px) ──
    Rectangle {
        id: ring3
        width: 270; height: 270
        radius: 135
        x: (parent.width - width) / 2
        y: (parent.height - height) / 2
        border.width: 0.8
        border.color: Qt.rgba(coreColor.r, coreColor.g, coreColor.b, 0.25 * glowIntensity)
        color: "transparent"
        transform: Rotation {
            origin.x: ring3.width / 2
            origin.y: ring3.height / 2
            angle: root.runningTime * root.ringDegPerSec("r3") % 360
        }
        Behavior on border.color { ColorAnimation { duration: 500; easing.type: Easing.OutCubic } }
    }

    // ── Layer 6: Inner Energy Ring (210px, thicker glow ring) ──
    Rectangle {
        id: ring4
        width: 210; height: 210
        radius: 105
        x: (parent.width - width) / 2
        y: (parent.height - height) / 2
        border.width: 2.0
        border.color: Qt.rgba(coreColor.r, coreColor.g, coreColor.b, 0.3 * glowIntensity)
        color: "transparent"
        transform: Rotation {
            origin.x: ring4.width / 2
            origin.y: ring4.height / 2
            angle: root.runningTime * root.ringDegPerSec("r4") % 360
        }
        Behavior on border.color { ColorAnimation { duration: 500; easing.type: Easing.OutCubic } }
    }

    // ── Layer 7: Innermost Ring (150px) ──
    Rectangle {
        id: ring5
        width: 150; height: 150
        radius: 75
        x: (parent.width - width) / 2
        y: (parent.height - height) / 2
        border.width: 1.2
        border.color: Qt.rgba(coreColor.r, coreColor.g, coreColor.b, 0.35 * glowIntensity)
        color: "transparent"
        transform: Rotation {
            origin.x: ring5.width / 2
            origin.y: ring5.height / 2
            angle: root.runningTime * root.ringDegPerSec("r5") % 360
        }
        Behavior on border.color { ColorAnimation { duration: 500; easing.type: Easing.OutCubic } }
    }

    // ── Layer 8: Listening ring (blue, 240px) ──
    Rectangle {
        id: listenRing
        width: 240; height: 240
        radius: 120
        x: (parent.width - width) / 2
        y: (parent.height - height) / 2
        border.width: 0.6
        border.color: Qt.rgba(51/255, 170/255, 255/255, 0.2 * glowIntensity)
        color: "transparent"
        visible: root.coreMode === "listening"
        opacity: visible ? 1 : 0
        transform: Rotation {
            origin.x: listenRing.width / 2
            origin.y: listenRing.height / 2
            angle: root.runningTime * 280 % 360
        }
        Behavior on opacity { NumberAnimation { duration: 400; easing.type: Easing.OutCubic } }
    }

    // ── Layer 9: Hexagonal Mesh (Canvas, 220px) ──
    Canvas {
        id: hexCanvas
        width: 220; height: 220
        x: (parent.width - width) / 2
        y: (parent.height - height) / 2
        antialiasing: true
        opacity: 0.15 + 0.1 * glowIntensity

        onPaint: {
            var ctx = getContext("2d")
            if (!ctx) return
            var w = width, h = height
            ctx.clearRect(0, 0, w, h)
            ctx.strokeStyle = Qt.rgba(coreColor.r, coreColor.g, coreColor.b, 0.4)
            ctx.lineWidth = 0.6

            var hexR = w * 0.05
            var cols = Math.ceil(w / (hexR * 1.8))
            var rows = Math.ceil(h / (hexR * 1.6))

            for (var row = 0; row < rows; row++) {
                for (var col = 0; col < cols; col++) {
                    var cx = col * hexR * 1.8 + (row % 2) * hexR * 0.9
                    var cy = row * hexR * 1.6
                    if (cx > w + hexR || cy > h + hexR) continue
                    ctx.beginPath()
                    for (var i = 0; i < 6; i++) {
                        var a = Math.PI / 3 * i - Math.PI / 6
                        var px = cx + hexR * Math.cos(a)
                        var py = cy + hexR * Math.sin(a)
                        if (i === 0) ctx.moveTo(px, py)
                        else ctx.lineTo(px, py)
                    }
                    ctx.closePath()
                    ctx.stroke()
                }
            }
        }
        Behavior on opacity { NumberAnimation { duration: 500 } }
    }

    // ── Layer 10: Inner Glow Sphere (120px) ──
    Canvas {
        width: 120; height: 120
        x: (parent.width - width) / 2
        y: (parent.height - height) / 2
        antialiasing: true
        opacity: 0.9 * (0.8 + 0.2 * (0.5 + 0.5 * Math.sin(root.breathe * Math.PI * 2)))
        onPaint: {
            var ctx = getContext("2d")
            if (!ctx) return
            var w = width, h = height, c = root.coreColor
            ctx.clearRect(0, 0, w, h)
            var grad = ctx.createRadialGradient(w/2, h/2, 0, w/2, h/2, w/2)
            grad.addColorStop(0, Qt.lighter(c, 1.6))
            grad.addColorStop(0.3, c)
            grad.addColorStop(0.6, Qt.darker(c, 1.3))
            grad.addColorStop(1, Qt.rgba(16/255, 5/255, 0, 0.5))
            ctx.fillStyle = grad
            ctx.beginPath()
            ctx.arc(w/2, h/2, w/2, 0, Math.PI * 2)
            ctx.fill()
        }
        Behavior on opacity { NumberAnimation { duration: 500; easing.type: Easing.OutCubic } }
    }

    // ── Layer 11: Bright Center Hotspot (50px) ──
    Canvas {
        width: 50; height: 50
        x: (parent.width - width) / 2
        y: (parent.height - height) / 2
        antialiasing: true
        opacity: 0.7 * (0.8 + 0.2 * (0.5 + 0.5 * Math.sin(root.breathe * Math.PI * 2)))
        onPaint: {
            var ctx = getContext("2d")
            if (!ctx) return
            var w = width, h = height, c = root.coreColor
            ctx.clearRect(0, 0, w, h)
            var grad = ctx.createRadialGradient(w/2, h/2, 0, w/2, h/2, w/2)
            grad.addColorStop(0, Qt.rgba(1, 1, 1, 0.9))
            grad.addColorStop(0.4, Qt.lighter(c, 1.4))
            grad.addColorStop(1, "transparent")
            ctx.fillStyle = grad
            ctx.beginPath()
            ctx.arc(w/2, h/2, w/2, 0, Math.PI * 2)
            ctx.fill()
        }
    }

    // ── Layer 12: Upper-Left Glare (200px) ──
    Canvas {
        width: 200; height: 200
        x: (parent.width - width) / 2 - 40
        y: (parent.height - height) / 2 - 40
        antialiasing: true
        opacity: glowIntensity * 0.5
        onPaint: {
            var ctx = getContext("2d")
            if (!ctx) return
            var w = width, h = height, c = root.coreColor
            ctx.clearRect(0, 0, w, h)
            var grad = ctx.createRadialGradient(w*0.3, h*0.3, 0, w*0.3, h*0.3, w*0.5)
            grad.addColorStop(0, Qt.rgba(255/255, 217/255, 102/255, 0.3 * glowIntensity))
            grad.addColorStop(0.4, Qt.rgba(c.r, c.g, c.b, 0.08))
            grad.addColorStop(1, "transparent")
            ctx.fillStyle = grad
            ctx.fillRect(0, 0, w, h)
        }
        Behavior on opacity { NumberAnimation { duration: 500; easing.type: Easing.OutCubic } }
    }

    // ── Layer 13: Bottom-Right Reflection (140px) ──
    Canvas {
        width: 140; height: 140
        x: (parent.width - width) / 2 + 40
        y: (parent.height - height) / 2 + 40
        antialiasing: true
        opacity: glowIntensity * 0.25
        onPaint: {
            var ctx = getContext("2d")
            if (!ctx) return
            var w = width, h = height, c = root.coreColor
            ctx.clearRect(0, 0, w, h)
            var grad = ctx.createRadialGradient(w*0.7, h*0.7, 0, w*0.7, h*0.7, w*0.5)
            grad.addColorStop(0, "transparent")
            grad.addColorStop(0.5, Qt.rgba(c.r, c.g, c.b, 0.05))
            grad.addColorStop(1, Qt.rgba(c.r, c.g, c.b, 0.1 * glowIntensity))
            ctx.fillStyle = grad
            ctx.fillRect(0, 0, w, h)
        }
        Behavior on opacity { NumberAnimation { duration: 500; easing.type: Easing.OutCubic } }
    }

    // ── Layer 14: Expanding Pulse Ring 1 ──
    Rectangle {
        property real p: root.pulseProgress
        readonly property real expandSize: 120 + p * (480 - 120)
        readonly property real expandOpacity: p < 0.78 ? (0.35 * (1 - p / 0.78)) : 0
        width: expandSize; height: expandSize
        radius: width / 2
        x: (parent.width - width) / 2
        y: (parent.height - height) / 2
        border.width: 1.2
        border.color: Qt.rgba(coreColor.r, coreColor.g, coreColor.b, 0.3 * glowIntensity * (expandOpacity / 0.35))
        color: "transparent"
        opacity: expandOpacity
        visible: opacity > 0.01
    }

    // ── Layer 15: Expanding Pulse Ring 2 (delayed) ──
    Rectangle {
        property real p: Math.max(0, (root.pulseProgress - 0.39) / 0.61)
        readonly property real expandSize: 120 + p * (480 - 120)
        readonly property real expandOpacity: p < 0.78 ? (0.25 * (1 - p / 0.78)) : 0
        width: expandSize; height: expandSize
        radius: width / 2
        x: (parent.width - width) / 2
        y: (parent.height - height) / 2
        border.width: 0.8
        border.color: Qt.rgba(coreColor.r, coreColor.g, coreColor.b, 0.2 * glowIntensity * (expandOpacity / 0.25))
        color: "transparent"
        opacity: expandOpacity
        visible: opacity > 0.01
    }

    // ── Layer 16: Outer Orbiting Lights (10 dots, continuous orbit) ──
    Repeater {
        model: 10
        Rectangle {
            readonly property real orbitRadius: [0.28, 0.35, 0.42, 0.48, 0.52, 0.30, 0.38, 0.44, 0.50, 0.55][index] * root.width
            // Angular speed in rad/s (converted from original cycles/3.2s)
            readonly property real orbitSpeed: [0.785, 1.374, 1.767, 2.159, 2.552, 0.982, 1.571, 1.963, 2.356, 1.178][index]
            readonly property real direction: index % 2 === 0 ? 1 : -1
            readonly property real dotSize: [2.5, 3.5, 2, 4, 3, 3, 2.5, 3, 4, 2][index]
            readonly property real phase: index * 0.628

            x: (parent.width - width) / 2 + orbitRadius * Math.cos(root.runningTime * orbitSpeed * direction + phase) - width / 2
            y: (parent.height - height) / 2 + orbitRadius * Math.sin(root.runningTime * orbitSpeed * direction + phase) - height / 2
            width: dotSize; height: dotSize
            radius: dotSize / 2
            color: Qt.lighter(coreColor, 1.3)
            opacity: 0.4 + 0.4 * (0.5 + 0.5 * Math.sin(root.runningTime * 3.927 + phase))
            Behavior on color { ColorAnimation { duration: 500; easing.type: Easing.OutCubic } }
        }
    }

    // ── Layer 17: Inner Orbiting Lights (8 smaller dots, continuous orbit) ──
    Repeater {
        model: 8
        Rectangle {
            readonly property real orbitRadius: [0.12, 0.17, 0.22, 0.27, 0.14, 0.19, 0.24, 0.29][index] * root.width
            readonly property real orbitSpeed: [2.356, 2.945, 3.534, 3.927, 2.552, 3.142, 3.730, 2.749][index]
            readonly property real direction: index % 2 === 0 ? 1 : -1
            readonly property real dotSize: [1.5, 2.5, 3.5, 2, 2, 3, 2.5, 1.5][index]
            readonly property real phase: index * 0.785

            x: (parent.width - width) / 2 + orbitRadius * Math.cos(root.runningTime * orbitSpeed * direction + phase) - width / 2
            y: (parent.height - height) / 2 + orbitRadius * Math.sin(root.runningTime * orbitSpeed * direction + phase) - height / 2
            width: dotSize; height: dotSize
            radius: dotSize / 2
            color: "#ffffff"
            opacity: 0.5 + 0.3 * (0.5 + 0.5 * Math.sin(root.runningTime * 5.890 + phase))
        }
    }

    // ── Layer 18: Bloom overlay (extra radial brightness) ──
    Canvas {
        width: 210; height: 210
        x: (parent.width - width) / 2
        y: (parent.height - height) / 2
        antialiasing: true
        opacity: 0.6 * glowIntensity * (0.8 + 0.2 * (0.5 + 0.5 * Math.sin(root.breathe * Math.PI * 2)))
        onPaint: {
            var ctx = getContext("2d")
            if (!ctx) return
            var w = width, h = height, c = root.coreColor
            ctx.clearRect(0, 0, w, h)
            var grad = ctx.createRadialGradient(w/2, h/2, 0, w/2, h/2, w/2)
            grad.addColorStop(0, Qt.rgba(1, 1, 1, 0.15))
            grad.addColorStop(0.3, Qt.rgba(c.r, c.g, c.b, 0.08))
            grad.addColorStop(0.6, Qt.rgba(c.r, c.g, c.b, 0.02))
            grad.addColorStop(1, "transparent")
            ctx.fillStyle = grad
            ctx.fillRect(0, 0, w, h)
        }
        Behavior on opacity { NumberAnimation { duration: 500; easing.type: Easing.OutCubic } }
    }

    // ── Mode color reactivity ──
    Behavior on coreColor {
        ColorAnimation { duration: 500; easing.type: Easing.OutCubic }
    }
    Behavior on glowIntensity {
        NumberAnimation { duration: 500; easing.type: Easing.OutCubic }
    }

    onCoreColorChanged: {
        for (var i = 0; i < children.length; i++) {
            if (children[i] instanceof Canvas) {
                children[i].requestPaint()
            }
        }
    }
    onGlowIntensityChanged: {
        for (var i = 0; i < children.length; i++) {
            if (children[i] instanceof Canvas) {
                children[i].requestPaint()
            }
        }
    }
}
