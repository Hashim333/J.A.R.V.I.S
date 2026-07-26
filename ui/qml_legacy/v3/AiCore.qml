import QtQuick 2.15
import QtQuick.Particles 2.15
import QtQuick.Effects

Item {
    id: aiCore
    width: theme.coreSize
    height: theme.coreSize

    Theme { id: theme }

    property string mode: bridge ? bridge.coreState : "idle"
    property real rotationSpeed: mode === "thinking" ? 3.0 : (mode === "listening" ? 0.5 : 1.0)
    property real breath: 0
    property real pulse: 0

    // --- Animations ---
    NumberAnimation on breath {
        from: 0; to: 1; duration: 3500; loops: Animation.Infinite; easing.type: Easing.InOutSine
    }
    SequentialAnimation on pulse {
        running: mode === "speaking"
        loops: Animation.Infinite
        NumberAnimation { from: 0; to: 1; duration: 800; easing.type: Easing.OutCubic }
        PauseAnimation { duration: 200 }
    }

    property color accentColor: theme.accentForMode(mode)
    Behavior on accentColor { ColorAnimation { duration: 800; easing.type: Easing.InOutCubic } }

    // --- Visuals Layer ---
    Item {
        id: coreVisuals
        anchors.fill: parent

        // --- Animated Rings ---
        AnimatedRings {
            anchors.fill: parent
            baseColor: accentColor
            rotationSpeed: rotationSpeed
            breath: breath
        }

        // --- Hexagonal Mesh ---
        Canvas {
            id: hexMesh
            anchors.fill: parent
            opacity: 0.15 + breath * 0.1
            rotation: baseRotation * 0.1
            property real baseRotation: 0
            NumberAnimation on baseRotation {
                from: 0; to: 360; duration: 120000; loops: Animation.Infinite
            }

            property real hexSize: 30
            
            onPaint: {
                var ctx = getContext("2d");
                ctx.reset();
                ctx.strokeStyle = accentColor;
                ctx.lineWidth = 1;

                var q = 2/3 * hexSize;
                var r = Math.sqrt(3)/3 * hexSize;

                for (var y = -hexSize; y < height + hexSize; y += r * 2) {
                    for (var x = -hexSize; x < width + hexSize; x += q * 3) {
                        drawHex(ctx, x, y, q);
                        drawHex(ctx, x + q * 1.5, y + r, q);
                    }
                }
            }

            function drawHex(ctx, x, y, size) {
                ctx.beginPath();
                for (var i = 0; i < 6; i++) {
                    var angle = Math.PI / 3 * i;
                    ctx.lineTo(x + size * Math.cos(angle), y + size * Math.sin(angle));
                }
                ctx.closePath();
                ctx.stroke();
            }

            Timer {
                interval: 33; running: true; repeat: true
                onTriggered: hexMesh.requestPaint()
            }
        }
        
        // --- Central Core ---
        Rectangle {
            anchors.centerIn: parent
            width: parent.width * 0.25 * (1 + breath * 0.1)
            height: width
            radius: width / 2
            color: accentColor
            opacity: 0.8
        }
        Rectangle {
            anchors.centerIn: parent
            width: parent.width * 0.15 * (1 + breath * 0.05)
            height: width
            radius: width / 2
            color: "#ffffff"
            opacity: 0.8
        }

        // --- Energy Pulse (Speaking) ---
        Rectangle {
            anchors.centerIn: parent
            width: parent.width * (0.2 + pulse * 0.8)
            height: width
            radius: width / 2
            color: "transparent"
            border.color: accentColor
            border.width: 4
            opacity: 1.0 - pulse
            visible: mode === "speaking"
        }
    }

    // --- Bloom Effect ---
    MultiEffect {
        anchors.fill: coreVisuals
        source: coreVisuals
        blurEnabled: true
        blur: 1.0
        blurMax: 32
        colorization: 1.0
        colorizationColor: accentColor
        opacity: 0.4 + breath * 0.2
    }

    // --- Particle Field ---
    ParticleSystem {
        id: particleSystem
        anchors.fill: parent
    }

    ImageParticle {
        system: particleSystem
        groups: ["sparks"]
        source: "qrc:/qt-project.org/imports/QtQuick/Particles/images/star.png"
        color: accentColor
        colorVariation: 0.5
        entryEffect: ImageParticle.Fade
        opacity: 0.8
    }

    Emitter {
        system: particleSystem
        group: "sparks"
        emitRate: 50
        lifeSpan: 2500
        size: 2
        sizeVariation: 1
        endSize: 0
        velocity: PointDirection { x: 0; y: 0; }
        acceleration: PointDirection { x: 0; y: 0; }
        x: width / 2
        y: height / 2
    }

    Wander {
        system: particleSystem
        groups: ["sparks"]
        xVariance: 50
        yVariance: 50
        pace: 100
    }
}
