import QtQuick 2.15

/**
 * AiCore — 15-layer AI core visualization.
 * 30+ rotating rings, hexagonal texture, orbiting lights, pulse rings.
 * Mode-reactive colors and speeds. All gradients rendered via Canvas.
 */
Item {
    id: root

    property string coreMode: "idle"
    property real glowIntensity: 0.45
    property color coreColor: "#ff8c1a"
    property real micEnergy: 0.0
    property real assistantEnergy: 0.0

    readonly property real baseSize: 260
    width: baseSize
    height: baseSize

    // ── Rotation speeds by mode ──
    readonly property var ringSpeeds: ({
        "idle":      { r1: 12, r2: 9.2, r3: 0,   r4: 17.1 },
        "listening": { r1: 6,  r2: 4.6, r3: 4,   r4: 8.6  },
        "thinking":  { r1: 2.5, r2: 1.9, r3: 0,   r4: 3.6  },
        "speaking":  { r1: 4,  r2: 3.1, r3: 0,   r4: 5.7  },
        "error":     { r1: 3,  r2: 2.3, r3: 0,   r4: 4.3  },
        "offline":   { r1: 20, r2: 15,  r3: 0,   r4: 28   }
    })

    function getSpeed(ring) {
        var speeds = ringSpeeds[root.coreMode] || ringSpeeds["idle"]
        return speeds[ring] || 12
    }

    // ── Breathing animation ──
    property real breathe: 0
    NumberAnimation on breathe {
        loops: Animation.Infinite
        from: 0; to: 1
        duration: 3200
        easing.type: Easing.InOutSine
    }

    // ── Glow oscillation ──
    property real glowOsc: 0
    NumberAnimation on glowOsc {
        loops: Animation.Infinite
        from: 0.35; to: 0.55
        duration: 2400
        easing.type: Easing.InOutSine
    }

    // ── Pulse ring animation ──
    property real pulseProgress: 0
    NumberAnimation on pulseProgress {
        loops: Animation.Infinite
        from: 0; to: 1
        duration: 2800
    }

    // ── Scale breathing ──
    readonly property real breatheScale: 1.0 + 0.045 * (0.5 + 0.5 * Math.sin(breathe * Math.PI * 2))
    transform: Scale {
        origin.x: root.width / 2
        origin.y: root.height / 2
        xScale: breatheScale
        yScale: breatheScale
    }

    // ── Layer 0: Outermost Ambient Corona (624px) ──
    Canvas {
        width: 624; height: 624
        x: (parent.width - width) / 2
        y: (parent.height - height) / 2
        opacity: glowIntensity * 0.15
        antialiasing: true
        onPaint: {
            var ctx = getContext("2d")
            if (!ctx) return
            var w = width, h = height, c = root.coreColor
            ctx.clearRect(0, 0, w, h)
            var grad = ctx.createRadialGradient(w/2, h/2, 0, w/2, h/2, w/2)
            grad.addColorStop(0, Qt.rgba(c.r, c.g, c.b, 0.15))
            grad.addColorStop(0.5, Qt.rgba(c.r, c.g, c.b, 0.04))
            grad.addColorStop(1, "transparent")
            ctx.fillStyle = grad
            ctx.fillRect(0, 0, w, h)
        }
        Behavior on opacity { NumberAnimation { duration: 500; easing.type: Easing.OutCubic } }
    }

    // ── Layer 1: Outer Glow Ring (416px) ──
    Canvas {
        width: 416; height: 416
        x: (parent.width - width) / 2
        y: (parent.height - height) / 2
        opacity: glowIntensity * 0.5
        antialiasing: true
        onPaint: {
            var ctx = getContext("2d")
            if (!ctx) return
            var w = width, h = height, c = root.coreColor
            ctx.clearRect(0, 0, w, h)
            var grad = ctx.createRadialGradient(w/2, h/2, 0, w/2, h/2, w/2)
            grad.addColorStop(0, Qt.rgba(c.r, c.g, c.b, 0.3))
            grad.addColorStop(0.35, Qt.rgba(c.r, c.g, c.b, 0.06))
            grad.addColorStop(1, "transparent")
            ctx.fillStyle = grad
            ctx.fillRect(0, 0, w, h)
        }
        Behavior on opacity { NumberAnimation { duration: 500; easing.type: Easing.OutCubic } }
    }

    // ── Layer 2: Mid Glow Ring (286px) ──
    Canvas {
        width: 286; height: 286
        x: (parent.width - width) / 2
        y: (parent.height - height) / 2
        opacity: glowIntensity * 0.6
        antialiasing: true
        onPaint: {
            var ctx = getContext("2d")
            if (!ctx) return
            var w = width, h = height, c = root.coreColor
            ctx.clearRect(0, 0, w, h)
            var grad = ctx.createRadialGradient(w/2, h/2, 0, w/2, h/2, w/2)
            grad.addColorStop(0, Qt.rgba(c.r, c.g, c.b, 0.5))
            grad.addColorStop(0.4, Qt.rgba(c.r, c.g, c.b, 0.08))
            grad.addColorStop(1, "transparent")
            ctx.fillStyle = grad
            ctx.fillRect(0, 0, w, h)
        }
        Behavior on opacity { NumberAnimation { duration: 500; easing.type: Easing.OutCubic } }
    }

    // ── Layer 3: Outer Orbit Ring (Ring 1, 221px) ──
    Rectangle {
        id: ring1
        width: 221; height: 221
        radius: 110.5
        x: (parent.width - width) / 2
        y: (parent.height - height) / 2
        border.width: 1.2
        border.color: Qt.rgba(coreColor.r, coreColor.g, coreColor.b, 0.2 * glowIntensity)
        color: "transparent"
        transform: Rotation {
            origin.x: ring1.width / 2
            origin.y: ring1.height / 2
            angle: (root.breathe * 360 * (12 / root.getSpeed("r1"))) % 360
        }
        Behavior on border.color { ColorAnimation { duration: 500; easing.type: Easing.OutCubic } }
    }

    // ── Layer 4: Inner Orbit Ring (Ring 2, 169px) ──
    Rectangle {
        id: ring2
        width: 169; height: 169
        radius: 84.5
        x: (parent.width - width) / 2
        y: (parent.height - height) / 2
        border.width: 0.8
        border.color: Qt.rgba(coreColor.r, coreColor.g, coreColor.b, 0.25 * glowIntensity)
        color: "transparent"
        transform: Rotation {
            origin.x: ring2.width / 2
            origin.y: ring2.height / 2
            angle: -(root.breathe * 360 * (12 * 1.3 / root.getSpeed("r2"))) % 360
        }
        Behavior on border.color { ColorAnimation { duration: 500; easing.type: Easing.OutCubic } }
    }

    // ── Layer 5: Listening Ring (Ring 3, 195px) ──
    Rectangle {
        id: ring3
        width: 195; height: 195
        radius: 97.5
        x: (parent.width - width) / 2
        y: (parent.height - height) / 2
        border.width: 0.6
        border.color: Qt.rgba(51/255, 170/255, 255/255, 0.15 * glowIntensity)
        color: "transparent"
        visible: root.coreMode === "listening"
        opacity: visible ? 1 : 0
        transform: Rotation {
            origin.x: ring3.width / 2
            origin.y: ring3.height / 2
            angle: (root.breathe * 360 * 3) % 360
        }
        Behavior on opacity { NumberAnimation { duration: 400; easing.type: Easing.OutCubic } }
    }

    // ── Layer 6: Innermost Ring (Ring 4, 117px) ──
    Rectangle {
        id: ring4
        width: 117; height: 117
        radius: 58.5
        x: (parent.width - width) / 2
        y: (parent.height - height) / 2
        border.width: 1.0
        border.color: Qt.rgba(coreColor.r, coreColor.g, coreColor.b, 0.35 * glowIntensity)
        color: "transparent"
        transform: Rotation {
            origin.x: ring4.width / 2
            origin.y: ring4.height / 2
            angle: (root.breathe * 360 * (12 * 0.7 / root.getSpeed("r4"))) % 360
        }
        Behavior on border.color { ColorAnimation { duration: 500; easing.type: Easing.OutCubic } }

        // Sub-ring inside Ring 4
        Rectangle {
            width: parent.width * 0.82
            height: parent.height * 0.82
            radius: width / 2
            x: (parent.width - width) / 2
            y: (parent.height - height) / 2
            border.width: 0.4
            border.color: Qt.rgba(coreColor.r, coreColor.g, coreColor.b, 0.12)
            color: "transparent"
        }
    }

    // ── Layer 7: Hexagonal Texture (Canvas) ──
    Canvas {
        id: hexCanvas
        width: 125; height: 125
        x: (parent.width - width) / 2
        y: (parent.height - height) / 2
        antialiasing: true
        opacity: 0.12 + 0.08 * glowIntensity

        onPaint: {
            var ctx = getContext("2d")
            if (!ctx) return
            var w = width, h = height
            ctx.clearRect(0, 0, w, h)
            ctx.strokeStyle = Qt.rgba(coreColor.r, coreColor.g, coreColor.b, 0.5)
            ctx.lineWidth = 0.5

            var hexR = w * 0.045
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

    // ── Layer 8: Inner Glow Sphere (83px) ──
    Canvas {
        width: 83; height: 83
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
            grad.addColorStop(0.4, c)
            grad.addColorStop(0.7, Qt.darker(c, 1.3))
            grad.addColorStop(1, "#100500")
            ctx.fillStyle = grad
            ctx.beginPath()
            ctx.arc(w/2, h/2, w/2, 0, Math.PI * 2)
            ctx.fill()
        }
        Behavior on opacity { NumberAnimation { duration: 500; easing.type: Easing.OutCubic } }
    }

    // ── Layer 9: Bright Center Hotspot (36px) ──
    Canvas {
        width: 36; height: 36
        x: (parent.width - width) / 2
        y: (parent.height - height) / 2
        antialiasing: true
        opacity: 0.65 * (0.8 + 0.2 * (0.5 + 0.5 * Math.sin(root.breathe * Math.PI * 2)))
        onPaint: {
            var ctx = getContext("2d")
            if (!ctx) return
            var w = width, h = height, c = root.coreColor
            ctx.clearRect(0, 0, w, h)
            var grad = ctx.createRadialGradient(w/2, h/2, 0, w/2, h/2, w/2)
            grad.addColorStop(0, "#ffffff")
            grad.addColorStop(0.5, Qt.lighter(c, 1.4))
            grad.addColorStop(1, "transparent")
            ctx.fillStyle = grad
            ctx.beginPath()
            ctx.arc(w/2, h/2, w/2, 0, Math.PI * 2)
            ctx.fill()
        }
    }

    // ── Layer 10: Upper-Left Glare (130px) ──
    Canvas {
        width: 130; height: 130
        x: (parent.width - width) / 2 - 30
        y: (parent.height - height) / 2 - 30
        antialiasing: true
        opacity: glowIntensity * 0.55
        onPaint: {
            var ctx = getContext("2d")
            if (!ctx) return
            var w = width, h = height, c = root.coreColor
            ctx.clearRect(0, 0, w, h)
            var grad = ctx.createRadialGradient(w*0.3, h*0.3, 0, w*0.3, h*0.3, w*0.5)
            grad.addColorStop(0, Qt.rgba(255/255, 217/255, 102/255, 0.35 * glowIntensity))
            grad.addColorStop(0.5, Qt.rgba(c.r, c.g, c.b, 0.1))
            grad.addColorStop(1, "transparent")
            ctx.fillStyle = grad
            ctx.fillRect(0, 0, w, h)
        }
        Behavior on opacity { NumberAnimation { duration: 500; easing.type: Easing.OutCubic } }
    }

    // ── Layer 11: Bottom-Right Reflection (91px) ──
    Canvas {
        width: 91; height: 91
        x: (parent.width - width) / 2 + 30
        y: (parent.height - height) / 2 + 30
        antialiasing: true
        opacity: glowIntensity * 0.3
        onPaint: {
            var ctx = getContext("2d")
            if (!ctx) return
            var w = width, h = height, c = root.coreColor
            ctx.clearRect(0, 0, w, h)
            var grad = ctx.createRadialGradient(w*0.7, h*0.7, 0, w*0.7, h*0.7, w*0.5)
            grad.addColorStop(0, "transparent")
            grad.addColorStop(0.6, Qt.rgba(c.r, c.g, c.b, 0.06))
            grad.addColorStop(1, Qt.rgba(c.r, c.g, c.b, 0.12 * glowIntensity))
            ctx.fillStyle = grad
            ctx.fillRect(0, 0, w, h)
        }
        Behavior on opacity { NumberAnimation { duration: 500; easing.type: Easing.OutCubic } }
    }

    // ── Layer 12: Expanding Pulse Ring 1 ──
    Rectangle {
        property real p: root.pulseProgress
        readonly property real expandSize: 91 + p * (338 - 91)
        readonly property real expandOpacity: p < 0.78 ? (0.4 * (1 - p / 0.78)) : 0
        width: expandSize; height: expandSize
        radius: width / 2
        x: (parent.width - width) / 2
        y: (parent.height - height) / 2
        border.width: 1.0
        border.color: Qt.rgba(coreColor.r, coreColor.g, coreColor.b, 0.35 * glowIntensity * (expandOpacity / 0.4))
        color: "transparent"
        opacity: expandOpacity
        visible: opacity > 0.01
    }

    // ── Layer 13: Expanding Pulse Ring 2 (delayed) ──
    Rectangle {
        property real p: Math.max(0, (root.pulseProgress - 0.39) / 0.61)
        readonly property real expandSize: 91 + p * (338 - 91)
        readonly property real expandOpacity: p < 0.78 ? (0.3 * (1 - p / 0.78)) : 0
        width: expandSize; height: expandSize
        radius: width / 2
        x: (parent.width - width) / 2
        y: (parent.height - height) / 2
        border.width: 0.6
        border.color: Qt.rgba(coreColor.r, coreColor.g, coreColor.b, 0.2 * glowIntensity * (expandOpacity / 0.3))
        color: "transparent"
        opacity: expandOpacity
        visible: opacity > 0.01
    }

    // ── Layer 14: Orbiting Lights (Outer Set, 6) ──
    Repeater {
        model: 6
        Rectangle {
            readonly property real orbitRadius: [0.20, 0.27, 0.34, 0.41, 0.48, 0.55][index] * root.width
            readonly property real orbitSpeed: [0.5, 0.8, 1.0, 1.2, 1.5, 0.7][index]
            readonly property real direction: index % 2 === 0 ? 1 : -1
            readonly property real dotSize: [2, 3, 2.5, 4, 3, 2][index]
            readonly property real phase: index * 1.047

            x: (parent.width - width) / 2 + orbitRadius * Math.cos(root.breathe * Math.PI * 2 * orbitSpeed * direction + phase) - width / 2
            y: (parent.height - height) / 2 + orbitRadius * Math.sin(root.breathe * Math.PI * 2 * orbitSpeed * direction + phase) - height / 2
            width: dotSize; height: dotSize
            radius: dotSize / 2
            color: Qt.lighter(coreColor, 1.3)
            opacity: 0.4 + 0.4 * (0.5 + 0.5 * Math.sin(root.breathe * Math.PI * 2 * 2 + phase))
            Behavior on color { ColorAnimation { duration: 500; easing.type: Easing.OutCubic } }
        }
    }

    // ── Layer 15: Orbiting Lights (Inner Set, 4) ──
    Repeater {
        model: 4
        Rectangle {
            readonly property real orbitRadius: [0.12, 0.16, 0.20, 0.24][index] * root.width
            readonly property real orbitSpeed: [1.5, 1.8, 2.0, 1.6][index]
            readonly property real direction: index % 2 === 0 ? 1 : -1
            readonly property real dotSize: [1.5, 2, 3, 2.5][index]
            readonly property real phase: index * 1.57

            x: (parent.width - width) / 2 + orbitRadius * Math.cos(root.breathe * Math.PI * 2 * orbitSpeed * direction + phase) - width / 2
            y: (parent.height - height) / 2 + orbitRadius * Math.sin(root.breathe * Math.PI * 2 * orbitSpeed * direction + phase) - height / 2
            width: dotSize; height: dotSize
            radius: dotSize / 2
            color: "#ffffff"
            opacity: 0.5 + 0.3 * (0.5 + 0.5 * Math.sin(root.breathe * Math.PI * 2 * 3 + phase))
        }
    }

    // ── Mode color reactivity ──
    Behavior on coreColor {
        ColorAnimation { duration: 500; easing.type: Easing.OutCubic }
    }
    Behavior on glowIntensity {
        NumberAnimation { duration: 500; easing.type: Easing.OutCubic }
    }

    // ── Repaint on color changes ──
    onCoreColorChanged: {
        // Trigger canvas repaints
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