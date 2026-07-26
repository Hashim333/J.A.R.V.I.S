import QtQuick 2.15

QtObject {
    // ── Brand Colors ──────────────────────────────────────────────
    readonly property color orange:        "#ff8c1a"
    readonly property color orangeLight:   "#ffa64d"
    readonly property color orangeDark:    "#cc6600"
    readonly property color orangeDim:     "#57320B"

    // ── Mode Colors ───────────────────────────────────────────────
    readonly property color listeningBlue: "#33aaff"
    readonly property color thinkingGold:  "#ffd700"
    readonly property color speakingOrange:"#ff8c1a"
    readonly property color errorRed:      "#ff3355"
    readonly property color offlineGray:   "#444444"

    // ── Status Colors ─────────────────────────────────────────────
    readonly property color onlineGreen:   "#00ff88"
    readonly property color micBlue:       "#33aaff"
    readonly property color speakerOrange: "#ff8c1a"
    readonly property color inactiveDot:   "#333333"

    // ── Background Colors ─────────────────────────────────────────
    readonly property color pureBlack:     "#000000"
    readonly property color deepSpace:     "#010101"
    readonly property color darkVoid:      "#030506"
    readonly property color warmDark:      "#0b0805"
    readonly property color panelDark:     Qt.rgba(8/255, 6/255, 5/255, 0.85)
    readonly property color panelDarker:   Qt.rgba(8/255, 6/255, 5/255, 0.90)
    readonly property color cardBg:        Qt.rgba(255/255, 255/255, 255/255, 0.03)
    readonly property color subtitleBg:    Qt.rgba(5/255, 6/255, 7/255, 0.70)

    // ── Text Colors ───────────────────────────────────────────────
    readonly property color textPrimary:   "#e8d5c4"
    readonly property color textSecondary: "#e0d5ca"
    readonly property color textTertiary:  "#998877"
    readonly property color textMuted:     "#776655"
    readonly property color textDim:       "#665544"
    readonly property color textFaint:     "#555544"
    readonly property color textClock:     Qt.rgba(207/255, 195/255, 186/255, 0.6)
    readonly property color textDate:      Qt.rgba(143/255, 131/255, 123/255, 0.4)
    readonly property color textStatusVal: "#e0e0e0"
    readonly property color textBadge:     "#aa8866"

    // ── Border Colors ─────────────────────────────────────────────
    readonly property color borderSubtle:  Qt.rgba(255/255, 140/255, 26/255, 0.08)
    readonly property color borderGlow:    Qt.rgba(255/255, 140/255, 26/255, 0.10)
    readonly property color borderBright:  Qt.rgba(255/255, 140/255, 26/255, 0.15)
    readonly property color borderBottom:  Qt.rgba(255/255, 140/255, 26/255, 0.06)

    // ── Fonts ─────────────────────────────────────────────────────
    readonly property string fontUI:       "Segoe UI"
    readonly property string fontMono:     "Consolas"

    // ── Layout Dimensions ─────────────────────────────────────────
    readonly property real sidebarWidth:   200
    readonly property real rightPanelWidth:240
    readonly property real bottomBarHeight:64
    readonly property real topBarHeight:   28
    readonly property real coreSize:       260
    readonly property real waveformWidth:  400
    readonly property real waveformHeight: 60
    readonly property real subtitleWidth:  500
    readonly property real subtitleHeight: 40

    // ── Reference Resolution ──────────────────────────────────────
    readonly property real refW: 1920
    readonly property real refH: 1080

    // ── Helper: Get accent color for mode ─────────────────────────
    function accentForMode(mode) {
        switch (mode) {
            case "listening": return listeningBlue
            case "thinking":  return thinkingGold
            case "speaking":  return orange
            case "error":     return errorRed
            case "offline":   return offlineGray
            default:          return orange
        }
    }

    // ── Helper: Get glow intensity for mode ───────────────────────
    function glowForMode(mode) {
        switch (mode) {
            case "listening": return 0.65
            case "thinking":  return 0.55
            case "speaking":  return 0.60
            case "error":     return 0.70
            case "offline":   return 0.15
            default:          return 0.45
        }
    }

    // ── Helper: Scale factor ──────────────────────────────────────
    function scale(w, h) {
        return Math.min(w / refW, h / refH)
    }
}