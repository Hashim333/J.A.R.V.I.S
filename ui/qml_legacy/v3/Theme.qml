import QtQuick 2.15

QtObject {
    readonly property color background: "#050505"
    readonly property color panelDark: Qt.rgba(8/255, 6/255, 5/255, 0.88)
    readonly property color panelGlass: Qt.rgba(255/255, 255/255, 255/255, 0.03)
    readonly property color borderSubtle: Qt.rgba(255/255, 152/255, 0/255, 0.08)
    readonly property color borderGlow: Qt.rgba(255/255, 152/255, 0/255, 0.15)
    readonly property color primary: "#ff9800"
    readonly property color accent: "#ffb347"
    readonly property color glow: "#ff8c00"
    readonly property color listening: "#00aaff"
    readonly property color thinking: "#ffd700"
    readonly property color errorColor: "#ff3355"
    readonly property color offlineColor: "#444444"
    readonly property color textPrimary: "#e8d5c4"
    readonly property color textSecondary: "#998877"
    readonly property color textMuted: "#776655"
    readonly property color textDim: "#665544"
    readonly property color textFaint: "#555544"
    readonly property color activeDot: "#00ff88"
    readonly property color micDot: "#33aaff"
    readonly property color speakerDot: "#ff8c1a"
    readonly property color inactiveDot: "#333333"

    readonly property real sidebarWidth: 200
    readonly property real rightPanelWidth: 240
    readonly property real bottomBarHeight: 64
    readonly property real topBarHeight: 28
    readonly property real coreSize: 260
    readonly property real waveformWidth: 400
    readonly property real waveformHeight: 60
    readonly property real subtitleWidth: 500
    readonly property real subtitleHeight: 40

    readonly property string fontUI: "Segoe UI"
    readonly property string fontMono: "Consolas"

    function accentForMode(mode) {
        switch (mode) {
            case "listening": return listening
            case "thinking": return thinking
            case "speaking": return primary
            case "error": return errorColor
            case "offline": return offlineColor
            default: return primary
        }
    }
}