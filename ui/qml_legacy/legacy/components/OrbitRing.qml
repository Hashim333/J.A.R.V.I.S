import QtQuick 2.15

Item {
    id: ringRoot

    // ── Properties ────────────────────────────────────────────────────
    property real ringSize: 200
    property real ringWidth: 1.5
    property color color: "#ff7b00"
    property real speed: 1.0
    property bool reverse: false
    property real startAngle: 0

    width: ringSize
    height: ringSize

    // ── Rotation animation ───────────────────────────────────────────
    RotationAnimation on rotation {
        id: rotAnim
        from: startAngle; to: startAngle + 360
        duration: Math.round(8000 / Math.max(speed, 0.1))
        loops: Animation.Infinite
        running: true
        direction: reverse ? RotationAnimation.Counterclockwise : RotationAnimation.Clockwise
    }

    onSpeedChanged: {
        rotAnim.duration = Math.round(8000 / Math.max(speed, 0.1))
    }

    // ── Ring canvas ──────────────────────────────────────────────────
    Canvas {
        id: canvas
        anchors.fill: parent

        onPaint: {
            var ctx = getContext("2d")
            var cx = width / 2
            var cy = height / 2
            var r = cx - ringWidth

            ctx.clearRect(0, 0, width, height)

            // Glow
            ctx.beginPath()
            ctx.arc(cx, cy, r + 2, 0, Math.PI * 2)
            ctx.strokeStyle = Qt.rgba(color.r, color.g, color.b, 0.15)
            ctx.lineWidth = ringWidth + 4
            ctx.stroke()

            // Main ring
            ctx.beginPath()
            ctx.arc(cx, cy, r, 0, Math.PI * 2)
            ctx.strokeStyle = color
            ctx.lineWidth = ringWidth
            ctx.stroke()

            // Inner highlight
            ctx.beginPath()
            ctx.arc(cx, cy, r - 1, 0, Math.PI * 2)
            ctx.strokeStyle = Qt.rgba(1, 1, 1, 0.08)
            ctx.lineWidth = 0.5
            ctx.stroke()
        }
    }

    onRingSizeChanged: { canvas.requestPaint() }
    onRingWidthChanged: { canvas.requestPaint() }
    onColorChanged: { canvas.requestPaint() }
    Component.onCompleted: { canvas.requestPaint() }
}
