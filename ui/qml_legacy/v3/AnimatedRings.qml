import QtQuick 2.15

Item {
    id: animatedRings
    
    property int ringCount: 30
    property color baseColor: theme.primary
    property real rotationSpeed: 1.0
    property real breath: 0.0

    Theme { id: theme }

    property real baseRotation: 0
    NumberAnimation on baseRotation {
        from: 0; to: 360; duration: 120000 / rotationSpeed; loops: Animation.Infinite
    }

    Repeater {
        model: ringCount
        delegate: Rectangle {
            id: ring
            width: animatedRings.width * (0.1 + (index / ringCount) * 0.9)
            height: width
            anchors.centerIn: parent
            radius: width / 2
            color: "transparent"
            
            property real randomSeed: Math.random()
            property real rotationFactor: (randomSeed - 0.5) * 4
            property real breathFactor: randomSeed * 0.2

            border.width: 1 + randomSeed * 1.5
            border.color: Qt.rgba(baseColor.r, baseColor.g, baseColor.b, 0.02 + (1 - (index/ringCount)) * 0.08)
            opacity: 0.1 + randomSeed * 0.4 + (Math.sin(breath * Math.PI * 2 + randomSeed * 10) * 0.5 + 0.5) * 0.2
            rotation: baseRotation * rotationFactor
            scale: 1.0 + (Math.sin(breath * Math.PI * 2 + randomSeed * 5) * 0.5 + 0.5) * breathFactor * 0.1
            
            Behavior on scale { NumberAnimation { duration: 200 } }
            Behavior on border.color { ColorAnimation { duration: 300 } }
        }
    }
}
