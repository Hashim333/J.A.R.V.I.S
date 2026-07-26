import QtQuick 2.15

/**
 * GlowLayer — renders a soft radial glow from the center using Canvas.
 * Used by AiCore and Dashboard for ambient lighting.
 */
Item {
    id: root

    property color glowColor: "#ff8c1a"
    property real glowIntensity: 0.45
    property real glowSize: 1.0 // multiplier of parent

    width: parent.width * glowSize
    height: parent.height * glowSize
    x: (parent.width - width) / 2
    y: (parent.height - height) / 2
    opacity: glowIntensity
    visible: opacity > 0.01

    Canvas {
        id: canvas
        anchors.fill: parent
        antialiasing: true

        onPaint: {
            var ctx = getContext("2d")
            if (!ctx) return
            var w = width, h = height
            ctx.clearRect(0, 0, w, h)

            var grad = ctx.createRadialGradient(w/2, h/2, 0, w/2, h/2, w/2)
            var c = root.glowColor
            grad.addColorStop(0, Qt.rgba(c.r, c.g, c.b, 0.35))
            grad.addColorStop(0.4, Qt.rgba(c.r, c.g, c.b, 0.08))
            grad.addColorStop(1, "transparent")
            ctx.fillStyle = grad
            ctx.fillRect(0, 0, w, h)
        }
    }

    onGlowColorChanged: canvas.requestPaint()
    onGlowIntensityChanged: canvas.requestPaint()
    onWidthChanged: canvas.requestPaint()
    onHeightChanged: canvas.requestPaint()

    Behavior on glowIntensity {
        NumberAnimation { duration: 500; easing.type: Easing.OutCubic }
    }
    Behavior on opacity {
        NumberAnimation { duration: 500; easing.type: Easing.OutCubic }
    }
}