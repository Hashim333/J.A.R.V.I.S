import QtQuick 2.15
import QtQuick.Particles 2.15

Item {
    id: particleBackground
    anchors.fill: parent

    property color particleColor: theme.primary

    Theme { id: theme }

    ParticleSystem {
        id: particleSystem
        anchors.fill: parent
    }

    ImageParticle {
        system: particleSystem
        groups: ["stars"]
        source: "qrc:/qt-project.org/imports/QtQuick/Particles/images/star.png"
        color: particleColor
        colorVariation: 0.3
        entryEffect: ImageParticle.Fade
        opacity: 0.6
    }

    Emitter {
        id: emitter
        system: particleSystem
        group: "stars"
        emitRate: 50
        lifeSpan: 5000
        lifeSpanVariation: 2000
        size: 2
        sizeVariation: 1
        endSize: 0
        velocity: PointDirection { x: 0; y: -10; xVariation: 5; yVariation: 5 }
        width: parent.width
        height: parent.height
    }

    Gravity {
        system: particleSystem
        groups: ["stars"]
        angle: 90
        magnitude: 2
    }

    Wander {
        system: particleSystem
        groups: ["stars"]
        xVariance: 10
        yVariance: 10
        pace: 100
    }
}
