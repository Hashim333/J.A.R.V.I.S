import QtQuick 2.15

Canvas {
    id: canvas

    // ── Config ───────────────────────────────────────────────────────
    property int count: (typeof uiConfig !== "undefined" && uiConfig.particle_count !== undefined) ? Math.max(uiConfig.particle_count, 800) : 800
    property string currentMode: "idle"

    // ── Mouse attraction ─────────────────────────────────────────────
    property real attractX: 0
    property real attractY: 0
    property bool mouseActive: false

    // ── Voice energy ─────────────────────────────────────────────────
    property real voiceEnergy: 0.0

    // ── Particle state arrays ────────────────────────────────────────
    property var _px: []
    property var _py: []
    property var _vx: []
    property var _vy: []
    property var _sz: []
    property var _ph: []
    property var _orb: []
    property var _layer: []

    // ── 60 fps tick + render ─────────────────────────────────────────
    Timer { interval: 16; running: true; repeat: true; onTriggered: { _tick(); canvas.requestPaint() } }

    Component.onCompleted: _init()

    function _init() {
        var c = Math.max(80, count)
        _px = []; _py = []; _vx = []; _vy = []; _sz = []; _ph = []; _orb = []; _layer = []
        for (var i = 0; i < c; i++) {
            _px[i] = Math.random() * canvas.width
            _py[i] = Math.random() * canvas.height
            _vx[i] = (Math.random() - 0.5) * 0.3
            _vy[i] = (Math.random() - 0.5) * 0.3
            _sz[i] = 0.3 + Math.random() * 2.5
            _ph[i] = Math.random() * Math.PI * 2
            _orb[i] = 0.2 + Math.random() * 0.8
            _layer[i] = Math.floor(Math.random() * 3)
        }
    }

    function _tick() {
        var w = canvas.width
        var h = canvas.height
        if (w <= 0 || h <= 0) return
        var cx = w / 2
        var cy = h / 2
        var mode = currentMode
        var t = Date.now() / 1000
        var c = _px.length
        var energy = voiceEnergy

        for (var i = 0; i < c; i++) {
            var dx = cx - _px[i]
            var dy = cy - _py[i]
            var dist = Math.sqrt(dx * dx + dy * dy) + 1
            var orbitFactor = _orb[i]
            var a

            switch (mode) {
                case "idle":
                    if (dist > w * 0.3) {
                        _vx[i] += (dx / dist) * 0.002 * orbitFactor
                        _vy[i] += (dy / dist) * 0.002 * orbitFactor
                    }
                    _vx[i] += Math.sin(t * 0.3 + _ph[i]) * 0.002
                    _vy[i] += Math.cos(t * 0.5 + _ph[i]) * 0.002
                    _vx[i] *= 0.99
                    _vy[i] *= 0.99
                    break

                case "listening":
                    _vx[i] += (dx / dist) * 0.03 * (1 - orbitFactor * 0.5)
                    _vy[i] += (dy / dist) * 0.03 * (1 - orbitFactor * 0.5)
                    a = Math.atan2(dy, dx) + Math.PI / 2
                    _vx[i] += Math.cos(a) * 0.004 * orbitFactor
                    _vy[i] += Math.sin(a) * 0.004 * orbitFactor
                    _vx[i] *= 0.94
                    _vy[i] *= 0.94
                    break

                case "thinking":
                    a = Math.atan2(dy, dx) + Math.PI / 2
                    _vx[i] += Math.cos(a) * 0.04 * orbitFactor * (1 - dist / (w * 0.35))
                    _vy[i] += Math.sin(a) * 0.04 * orbitFactor * (1 - dist / (w * 0.35))
                    _vx[i] += (dx / dist) * 0.006
                    _vy[i] += (dy / dist) * 0.006
                    _vx[i] *= 0.95
                    _vy[i] *= 0.95
                    break

                case "speaking":
                    a = Math.atan2(_py[i] - cy, _px[i] - cx)
                    var wave = Math.sin(a * 4 + t * 4 + energy * 8) * (0.2 + 0.8 * energy)
                    _vx[i] += Math.cos(a) * wave * 0.015
                    _vy[i] += Math.sin(a) * wave * 0.015
                    _vx[i] += (dx / dist) * 0.01 * (1 - energy)
                    _vy[i] += (dy / dist) * 0.01 * (1 - energy)
                    _vx[i] *= 0.96
                    _vy[i] *= 0.96
                    break

                case "error":
                    _vx[i] += (Math.random() - 0.5) * 0.08
                    _vy[i] += (Math.random() - 0.5) * 0.08
                    _vx[i] *= 0.93
                    _vy[i] *= 0.93
                    break

                case "offline":
                    _vx[i] *= 0.99
                    _vy[i] *= 0.99
                    break
            }

            if (mouseActive && attractX > 0 && attractY > 0) {
                var mdx = attractX - _px[i]
                var mdy = attractY - _py[i]
                var mdist = Math.sqrt(mdx * mdx + mdy * mdy) + 1
                _vx[i] += (mdx / mdist) * 0.03 * _layer[i]
                _vy[i] += (mdy / mdist) * 0.03 * _layer[i]
            }

            _px[i] += _vx[i]
            _py[i] += _vy[i]

            if (_px[i] < -30) _px[i] = w + 30
            if (_px[i] > w + 30) _px[i] = -30
            if (_py[i] < -30) _py[i] = h + 30
            if (_py[i] > h + 30) _py[i] = -30
        }
    }

    // ── Canvas painting (GPU accelerated) ────────────────────────────
    onPaint: {
        var ctx = canvas.getContext("2d")
        var w = canvas.width
        var h = canvas.height
        ctx.clearRect(0, 0, w, h)

        var mode = currentMode
        var t = Date.now() / 1000
        var c = _px.length
        var energy = voiceEnergy

        for (var layer = 0; layer < 3; layer++) {
            for (var i = 0; i < c; i++) {
                if (_layer[i] !== layer) continue
                if (_px[i] === undefined) continue

                var x = _px[i]
                var y = _py[i]
                var base = _sz[i]
                var phase = _ph[i]
                var depthOpacity = 0.3 + layer * 0.35

                var opacity, color, size

                switch (mode) {
                    case "idle":
                        opacity = depthOpacity * (0.1 + 0.15 * Math.sin(t * 0.4 + phase))
                        color = "#ff7b00"
                        size = base
                        break
                    case "listening":
                        opacity = depthOpacity * (0.2 + 0.35 * Math.sin(t * 2.5 + phase))
                        var blueMix = Math.min(1.0, 0.3 + 0.7 * (0.5 + 0.5 * Math.sin(t * 0.5)))
                        var r = 0.2 + 0.8 * (1 - blueMix)
                        var g = 0.4 + 0.5 * (1 - blueMix)
                        var b = 0.7 + 0.3 * blueMix
                        color = Qt.rgba(r, g, b, 1.0)
                        size = base * (1.0 + 0.5 * (0.5 + 0.5 * Math.sin(t * 2 + phase)))
                        break
                    case "thinking":
                        opacity = depthOpacity * (0.15 + 0.35 * Math.sin(t * 3.5 + phase))
                        color = "#ffd700"
                        size = base * (0.8 + 0.6 * (0.5 + 0.5 * Math.sin(t * 3 + phase)))
                        break
                    case "speaking":
                        var brightness = 0.2 + 0.6 * energy
                        opacity = depthOpacity * (0.15 + brightness * 0.7 * (0.5 + 0.5 * Math.sin(t * 5 + phase)))
                        color = Qt.rgba(1.0, 0.5 + 0.3 * energy, 0.0, 1.0)
                        size = base * (0.8 + 1.2 * energy * (0.5 + 0.5 * Math.sin(t * 5 + phase)))
                        break
                    case "error":
                        opacity = depthOpacity * (0.2 + 0.5 * Math.random())
                        color = "#ff3355"
                        size = base * (0.8 + 0.8 * Math.random())
                        break
                    case "offline":
                        opacity = depthOpacity * 0.06
                        color = "#666666"
                        size = base
                        break
                    default:
                        opacity = 0.1
                        color = "#ff7b00"
                        size = base
                }

                ctx.globalAlpha = Math.max(0.0, Math.min(1.0, opacity))
                ctx.fillStyle = color
                ctx.beginPath()
                ctx.arc(x, y, Math.max(0.3, size / 2), 0, Math.PI * 2)
                ctx.fill()

                if (opacity > 0.3 && size > 1.5) {
                    ctx.globalAlpha = opacity * 0.3
                    ctx.beginPath()
                    ctx.arc(x, y, Math.max(0.5, size), 0, Math.PI * 2)
                    ctx.fill()
                }
            }
        }

        ctx.globalAlpha = 1.0
    }

    onWidthChanged: { _init(); canvas.requestPaint() }
    onHeightChanged: { _init(); canvas.requestPaint() }
}