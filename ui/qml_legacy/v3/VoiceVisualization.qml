import QtQuick 2.15

Item {
    id: voiceVis
    width: 200
    height: 60

    Theme { id: theme }

    property real energy: bridge ? (bridge.micEnergy + bridge.assistantEnergy) * 0.5 : 0.5
    property string mode: bridge ? bridge.coreState : "idle"

    property color waveColor: theme.accentForMode(mode)
    Behavior on waveColor { ColorAnimation { duration: 300 } }
    
    property real phase: 0
    NumberAnimation on phase { from: 0; to: Math.PI * 2; duration: 1000; loops: Animation.Infinite }

    Canvas {
        id: canvas
        anchors.fill: parent

        onPaint: {
            var ctx = getContext("2d");
            ctx.reset();

            var grd = ctx.createLinearGradient(0, 0, 0, height);
            grd.addColorStop(0, Qt.rgba(waveColor.r, waveColor.g, waveColor.b, 0.0));
            grd.addColorStop(0.5, Qt.rgba(waveColor.r, waveColor.g, waveColor.b, 0.8 * energy));
            grd.addColorStop(1, Qt.rgba(waveColor.r, waveColor.g, waveColor.b, 0.0));
            ctx.strokeStyle = grd;
            
            ctx.lineWidth = 2.5;

            ctx.beginPath();
            var y_center = height / 2;
            var x_space = width / 100;
            for (var i = 0; i <= 100; i++) {
                var x = i * x_space;
                var angle = phase + i * 0.2;
                var y = y_center + Math.sin(angle) * (height / 3) * energy;
                if (i === 0) {
                    ctx.moveTo(x, y);
                } else {
                    ctx.lineTo(x, y);
                }
            }
            ctx.stroke();
        }

        Timer {
            interval: 16; running: true; repeat: true
            onTriggered: canvas.requestPaint()
        }
    }
}
