import QtQuick 2.15

Item {
    id: root

    property string coreMode: "idle"
    property real glowIntensity: 0.45
    property color coreColor: "#ff8c1a"
    property real micEnergy: 0.0
    property real assistantEnergy: 0.0
    property bool animated: true

    property real baseSize: 620
    readonly property real uiScale: baseSize / 260
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

    property real runningTime: 0
    Timer {
        interval: 33
        running: root.animated
        repeat: true
        onTriggered: root.runningTime += 0.033
    }

    property real breathe: 0
    NumberAnimation on breathe {
        loops: Animation.Infinite
        running: root.animated
        from: 0; to: 1
        duration: 3200
        easing.type: Easing.InOutSine
    }

    property real glowOsc: 0
    NumberAnimation on glowOsc {
        loops: Animation.Infinite
        running: root.animated
        from: 0.35; to: 0.65
        duration: 2400
        easing.type: Easing.InOutSine
    }

    property real pulseProgress: 0
    NumberAnimation on pulseProgress {
        loops: Animation.Infinite
        running: root.animated
        from: 0; to: 1
        duration: 2800
    }

    readonly property real breatheScale: 1.0 + 0.04 * (0.5 + 0.5 * Math.sin(breathe * Math.PI * 2))
    transform: Scale {
        origin.x: root.width / 2
        origin.y: root.height / 2
        xScale: breatheScale
        yScale: breatheScale
    }

    onCoreModeChanged: root.coreColor = root.modeColor()
    Component.onCompleted: root.coreColor = root.modeColor()

    function requestCanvasRefresh() {
        function visit(item) {
            if (!item || !item.children) return
            for (var i = 0; i < item.children.length; i++) {
                if (item.children[i] instanceof Canvas) {
                    item.children[i].requestPaint()
                }
                visit(item.children[i])
            }
        }
        visit(root)
    }

    onCoreColorChanged: requestCanvasRefresh()
    onGlowIntensityChanged: requestCanvasRefresh()

    Item {
        id: scaledCore
        width: 260
        height: 260
        x: (parent.width - width) / 2
        y: (parent.height - height) / 2
        scale: root.uiScale
        transformOrigin: Item.Center
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
            grad.addColorStop(0.35, Qt.rgba(c.r, c.g, c.b, 0.04))
            grad.addColorStop(1, "transparent")
            ctx.fillStyle = grad
            ctx.fillRect(0, 0, w, h)
        }
    }

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
            grad.addColorStop(0, Qt.rgba(c.r, c.g, c.b, 0.30))
            grad.addColorStop(0.35, Qt.rgba(c.r, c.g, c.b, 0.06))
            grad.addColorStop(1, "transparent")
            ctx.fillStyle = grad
            ctx.fillRect(0, 0, w, h)
        }
    }

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
            grad.addColorStop(0, Qt.rgba(c.r, c.g, c.b, 0.50))
            grad.addColorStop(0.35, Qt.rgba(c.r, c.g, c.b, 0.08))
            grad.addColorStop(1, "transparent")
            ctx.fillStyle = grad
            ctx.fillRect(0, 0, w, h)
        }
    }

    Rectangle {
        id: ring1
        width: 221; height: 221
        radius: 110.5
        x: (parent.width - width) / 2
        y: (parent.height - height) / 2
        border.width: 1.2
        border.color: Qt.rgba(coreColor.r, coreColor.g, coreColor.b, 0.20 * glowIntensity)
        color: "transparent"
        transform: Rotation {
            origin.x: ring1.width / 2
            origin.y: ring1.height / 2
            angle: root.runningTime * root.ringDegPerSec("r1") % 360
        }
    }

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
            angle: root.runningTime * root.ringDegPerSec("r2") % 360
        }
    }

    Rectangle {
        id: listenRing
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
            origin.x: listenRing.width / 2
            origin.y: listenRing.height / 2
            angle: root.runningTime * 280 % 360
        }
        Behavior on opacity { NumberAnimation { duration: 400; easing.type: Easing.OutCubic } }
    }

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
            angle: root.runningTime * root.ringDegPerSec("r4") % 360
        }
    }

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
    }

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
            grad.addColorStop(0.3, c)
            grad.addColorStop(0.6, Qt.darker(c, 1.3))
            grad.addColorStop(1, Qt.rgba(16/255, 5/255, 0, 0.5))
            ctx.fillStyle = grad
            ctx.beginPath()
            ctx.arc(w/2, h/2, w/2, 0, Math.PI * 2)
            ctx.fill()
        }
    }

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
            grad.addColorStop(0, Qt.rgba(1, 1, 1, 0.9))
            grad.addColorStop(0.4, Qt.lighter(c, 1.4))
            grad.addColorStop(1, "transparent")
            ctx.fillStyle = grad
            ctx.beginPath()
            ctx.arc(w/2, h/2, w/2, 0, Math.PI * 2)
            ctx.fill()
        }
    }

    Canvas {
        width: 130; height: 130
        x: (parent.width - width) / 2 - 28
        y: (parent.height - height) / 2 - 28
        antialiasing: true
        opacity: glowIntensity * 0.55
        onPaint: {
            var ctx = getContext("2d")
            if (!ctx) return
            var w = width, h = height, c = root.coreColor
            ctx.clearRect(0, 0, w, h)
            var grad = ctx.createRadialGradient(w*0.3, h*0.3, 0, w*0.3, h*0.3, w*0.5)
            grad.addColorStop(0, Qt.rgba(255/255, 217/255, 102/255, 0.35 * glowIntensity))
            grad.addColorStop(0.4, Qt.rgba(c.r, c.g, c.b, 0.10))
            grad.addColorStop(1, "transparent")
            ctx.fillStyle = grad
            ctx.fillRect(0, 0, w, h)
        }
    }

    Canvas {
        width: 91; height: 91
        x: (parent.width - width) / 2 + 18
        y: (parent.height - height) / 2 + 18
        antialiasing: true
        opacity: glowIntensity * 0.30
        onPaint: {
            var ctx = getContext("2d")
            if (!ctx) return
            var w = width, h = height, c = root.coreColor
            ctx.clearRect(0, 0, w, h)
            var grad = ctx.createRadialGradient(w*0.7, h*0.7, 0, w*0.7, h*0.7, w*0.5)
            grad.addColorStop(0, "transparent")
            grad.addColorStop(0.5, Qt.rgba(c.r, c.g, c.b, 0.12 * glowIntensity))
            grad.addColorStop(1, Qt.rgba(c.r, c.g, c.b, 0.15 * glowIntensity))
            ctx.fillStyle = grad
            ctx.fillRect(0, 0, w, h)
        }
    }

    Rectangle {
        property real p: root.pulseProgress
        readonly property real expandSize: 91 + p * (338 - 91)
        readonly property real expandOpacity: p < 0.78 ? (0.40 * (1 - p / 0.78)) : 0
        width: expandSize; height: expandSize
        radius: width / 2
        x: (parent.width - width) / 2
        y: (parent.height - height) / 2
        border.width: 1.0
        border.color: Qt.rgba(coreColor.r, coreColor.g, coreColor.b, 0.35 * glowIntensity * (expandOpacity / 0.40))
        color: "transparent"
        opacity: expandOpacity
        visible: opacity > 0.01
    }

    Rectangle {
        property real p: Math.max(0, (root.pulseProgress - 0.39) / 0.61)
        readonly property real expandSize: 91 + p * (338 - 91)
        readonly property real expandOpacity: p < 0.78 ? (0.25 * (1 - p / 0.78)) : 0
        width: expandSize; height: expandSize
        radius: width / 2
        x: (parent.width - width) / 2
        y: (parent.height - height) / 2
        border.width: 0.6
        border.color: Qt.rgba(coreColor.r, coreColor.g, coreColor.b, 0.20 * glowIntensity * (expandOpacity / 0.25))
        color: "transparent"
        opacity: expandOpacity
        visible: opacity > 0.01
    }

    Repeater {
        model: 6
        Rectangle {
            readonly property real orbitRadius: [0.20, 0.27, 0.34, 0.41, 0.48, 0.55][index] * root.width
            readonly property real orbitSpeed: [0.90, 1.25, 1.65, 2.00, 2.35, 1.10][index]
            readonly property real direction: index % 2 === 0 ? 1 : -1
            readonly property real dotSize: [2.0, 2.8, 3.2, 3.8, 3.0, 2.4][index]
            readonly property real phase: index * 0.65
            x: (parent.width - width) / 2 + orbitRadius * Math.cos(root.runningTime * orbitSpeed * direction + phase) - width / 2
            y: (parent.height - height) / 2 + orbitRadius * Math.sin(root.runningTime * orbitSpeed * direction + phase) - height / 2
            width: dotSize; height: dotSize
            radius: dotSize / 2
            color: Qt.lighter(coreColor, 1.3)
            opacity: 0.45 + 0.25 * (0.5 + 0.5 * Math.sin(root.runningTime * 3.9 + phase))
        }
    }

    Repeater {
        model: 4
        Rectangle {
            readonly property real orbitRadius: [0.12, 0.16, 0.20, 0.24][index] * root.width
            readonly property real orbitSpeed: [2.0, 2.5, 3.0, 3.4][index]
            readonly property real direction: index % 2 === 0 ? 1 : -1
            readonly property real dotSize: [1.4, 2.2, 2.7, 1.8][index]
            readonly property real phase: index * 0.75
            x: (parent.width - width) / 2 + orbitRadius * Math.cos(root.runningTime * orbitSpeed * direction + phase) - width / 2
            y: (parent.height - height) / 2 + orbitRadius * Math.sin(root.runningTime * orbitSpeed * direction + phase) - height / 2
            width: dotSize; height: dotSize
            radius: dotSize / 2
            color: "#ffffff"
            opacity: 0.55 + 0.20 * (0.5 + 0.5 * Math.sin(root.runningTime * 5.8 + phase))
        }
    }

    Canvas {
        width: 210; height: 210
        x: (parent.width - width) / 2
        y: (parent.height - height) / 2
        antialiasing: true
        opacity: 0.60 * glowIntensity * (0.8 + 0.2 * (0.5 + 0.5 * Math.sin(root.breathe * Math.PI * 2)))
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
    }

    }

    Behavior on coreColor { ColorAnimation { duration: 500; easing.type: Easing.OutCubic } }
    Behavior on glowIntensity { NumberAnimation { duration: 500; easing.type: Easing.OutCubic } }
}
