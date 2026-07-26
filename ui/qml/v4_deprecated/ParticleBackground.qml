import QtQuick 2.15
import QtQuick.Window 2.15

/**
 * ParticleBackground — 800-particle system rendered on Canvas.
 * 3 depth layers, mode-reactive colors, orbital/attraction behaviors.
 */
Item {
    id: root

    property string coreMode: "idle"
    property real micEnergy: 0.0
    property real assistantEnergy: 0.0
    property real glowIntensity: 0.45
    property color coreColor: "#ff8c1a"

    readonly property int particleCount: 800
    readonly property real centerX: width / 2
    readonly property real centerY: height / 2

    Canvas {
        id: canvas
        anchors.fill: parent
        antialiasing: true

        property var particles: []

        onPaint: {
            var ctx = getContext("2d")
            if (!ctx) return
            var w = canvas.width
            var h = canvas.height
            ctx.clearRect(0, 0, w, h)

            // Draw ambient glow field
            var ambientGrad = ctx.createRadialGradient(w/2, h/2, 0, w/2, h/2, w*0.6)
            var isListening = coreMode === "listening"
            if (isListening) {
                ambientGrad.addColorStop(0, Qt.rgba(0, 0.1, 0.2, 0.3 * glowIntensity))
                ambientGrad.addColorStop(0.5, Qt.rgba(0, 0.05, 0.1, 0.1 * glowIntensity))
            } else {
                ambientGrad.addColorStop(0, Qt.rgba(0.29, 0.13, 0, 0.3 * glowIntensity))
                ambientGrad.addColorStop(0.4, Qt.rgba(0.09, 0.04, 0, 0.1 * glowIntensity))
            }
            ambientGrad.addColorStop(1, "transparent")
            ctx.fillStyle = ambientGrad
            ctx.fillRect(0, 0, w, h)

            // Draw particles
            var p, px, py, alpha, size, r, g, b
            for (var i = 0; i < particles.length; i++) {
                p = particles[i]
                px = p.x
                py = p.y
                alpha = p.alpha * p.brightness
                size = p.size

                if (alpha < 0.01 || size < 0.1) continue

                // Layer depth opacity
                if (p.layer === 0) alpha *= 0.3
                else if (p.layer === 1) alpha *= 0.65

                ctx.globalAlpha = alpha
                ctx.beginPath()
                ctx.arc(px, py, size, 0, Math.PI * 2)

                // Color
                r = p.r; g = p.g; b = p.b
                ctx.fillStyle = Qt.rgba(r, g, b, 1)
                ctx.fill()

                // Glow for larger particles
                if (alpha > 0.3 && size > 1.5) {
                    ctx.globalAlpha = alpha * 0.3
                    ctx.beginPath()
                    ctx.arc(px, py, size * 2, 0, Math.PI * 2)
                    ctx.fill()
                }
            }
        }

        function initParticles() {
            particles = []
            var w = canvas.width
            var h = canvas.height
            for (var i = 0; i < particleCount; i++) {
                particles.push({
                    x: Math.random() * w,
                    y: Math.random() * h,
                    vx: (Math.random() - 0.5) * 0.3,
                    vy: (Math.random() - 0.5) * 0.3,
                    size: 0.3 + Math.random() * 2.2,
                    phase: Math.random() * Math.PI * 2,
                    orbitalTendency: 0.2 + Math.random() * 0.8,
                    layer: Math.floor(Math.random() * 3),
                    brightness: 0.5 + Math.random() * 0.5,
                    alpha: 0.1 + Math.random() * 0.15,
                    r: 1.0, g: 0.55, b: 0.1
                })
            }
        }

        function updateParticles(dt) {
            var t = Date.now() * 0.001
            var w = canvas.width
            var h = canvas.height
            var cx = w / 2
            var cy = h / 2
            var mode = root.coreMode
            var energy = root.micEnergy
            var p, dx, dy, dist, speed, wave, blueMix, angle

            for (var i = 0; i < particles.length; i++) {
                p = particles[i]
                dx = cx - p.x
                dy = cy - p.y
                dist = Math.sqrt(dx * dx + dy * dy)
                angle = Math.atan2(dy, dx)

                // ── Mode-specific behavior ──
                switch (mode) {
                    case "idle":
                        // Gentle drift
                        p.vx += (Math.random() - 0.5) * 0.02
                        p.vy += (Math.random() - 0.5) * 0.02
                        // Slow pull toward center if far
                        if (dist > w * 0.3) {
                            p.vx += dx * 0.0001
                            p.vy += dy * 0.0001
                        }
                        // Damping
                        p.vx *= 0.99
                        p.vy *= 0.99
                        // Clamp velocity
                        speed = Math.sqrt(p.vx * p.vx + p.vy * p.vy)
                        if (speed > 0.3) { p.vx *= 0.3 / speed; p.vy *= 0.3 / speed }
                        // Color: warm orange
                        p.r = 1.0; p.g = 0.55; p.b = 0.1
                        // Alpha: slow pulse
                        p.alpha = 0.1 + 0.15 * (0.5 + 0.5 * Math.sin(t * 0.4 + p.phase))
                        break

                    case "listening":
                        // Strong attraction to center
                        p.vx += dx * 0.002
                        p.vy += dy * 0.002
                        // Orbital component
                        p.vx += -dy * 0.0005 * p.orbitalTendency
                        p.vy += dx * 0.0005 * p.orbitalTendency
                        p.vx *= 0.97
                        p.vy *= 0.97
                        // Blue shift
                        blueMix = Math.min(1.0, 0.3 + 0.7 * (0.5 + 0.5 * Math.sin(t * 0.5)))
                        p.r = 0.2 + 0.8 * (1 - blueMix)
                        p.g = 0.4 + 0.5 * (1 - blueMix)
                        p.b = 0.7 + 0.3 * blueMix
                        // Faster pulse
                        p.alpha = 0.2 + 0.35 * (0.5 + 0.5 * Math.sin(t * 2.5 + p.phase))
                        p.size = (0.3 + Math.random() * 2.2) * (1.0 + 0.5 * (0.5 + 0.5 * Math.sin(t * 2.5 + p.phase)))
                        break

                    case "thinking":
                        // Fast orbital motion
                        p.vx += -dy * 0.003 * p.orbitalTendency
                        p.vy += dx * 0.003 * p.orbitalTendency
                        // Tight convergence
                        p.vx += dx * 0.001
                        p.vy += dy * 0.001
                        p.vx *= 0.96
                        p.vy *= 0.96
                        // Gold
                        p.r = 1.0; p.g = 0.84; p.b = 0.0
                        p.alpha = 0.15 + 0.35 * (0.5 + 0.5 * Math.sin(t * 3.5 + p.phase))
                        p.size = (0.3 + Math.random() * 2.2) * (0.8 + 0.6 * (0.5 + 0.5 * Math.sin(t * 3.5 + p.phase)))
                        break

                    case "speaking":
                        // Voice-driven radial waves (4 lobes)
                        wave = Math.sin(angle * 4 + t * 4 + energy * 8) * (0.2 + 0.8 * energy)
                        p.vx += Math.cos(angle) * wave * 0.5
                        p.vy += Math.sin(angle) * wave * 0.5
                        p.vx *= 0.95
                        p.vy *= 0.95
                        // Orange brightness scales with energy
                        p.r = 1.0
                        p.g = 0.5 + 0.3 * energy
                        p.b = 0.0
                        p.alpha = 0.15 + p.brightness * 0.7 * (0.5 + 0.5 * Math.sin(t * 5 + p.phase))
                        p.size = (0.3 + Math.random() * 2.2) * (0.8 + 1.2 * energy * (0.5 + 0.5 * Math.sin(t * 5 + p.phase)))
                        break

                    case "error":
                        // Chaotic bursts
                        p.vx += (Math.random() - 0.5) * 0.5
                        p.vy += (Math.random() - 0.5) * 0.5
                        p.vx *= 0.9
                        p.vy *= 0.9
                        p.r = 1.0; p.g = 0.2; p.b = 0.33
                        p.alpha = 0.2 + 0.5 * Math.random()
                        p.size = (0.3 + Math.random() * 2.2) * (0.8 + 0.8 * Math.random())
                        break

                    case "offline":
                        // Almost still
                        p.vx *= 0.98
                        p.vy *= 0.98
                        p.r = 0.4; p.g = 0.4; p.b = 0.4
                        p.alpha = 0.02 + 0.04 * (0.5 + 0.5 * Math.sin(t * 0.1 + p.phase))
                        break
                }

                // Update position
                p.x += p.vx
                p.y += p.vy

                // Wrap around edges
                if (p.x < -10) p.x = w + 10
                if (p.x > w + 10) p.x = -10
                if (p.y < -10) p.y = h + 10
                if (p.y > h + 10) p.y = -10
            }
        }

    }

    Timer {
        id: animTimer
        interval: 16
        running: true
        repeat: true
        property real lastTimestamp: 0
        onTriggered: {
            var now = Date.now()
            if (lastTimestamp === 0) lastTimestamp = now
            var dt = Math.min((now - lastTimestamp) / 1000, 0.05)
            lastTimestamp = now
            if (canvas.particles.length === 0) canvas.initParticles()
            canvas.updateParticles(dt)
            canvas.requestPaint()
        }
    }

    onWidthChanged: { canvas.initParticles() }
    onHeightChanged: { canvas.initParticles() }
}