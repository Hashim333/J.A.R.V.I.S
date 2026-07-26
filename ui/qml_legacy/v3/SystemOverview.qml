import QtQuick 2.15
import QtQuick.Controls 2.15
import QtQuick.Layouts 1.15

Rectangle {
    id: systemOverview
    color: theme.panelGlass
    border.color: theme.borderSubtle
    border.width: 1
    radius: 8

    Theme { id: theme }

    property real cpuUsage: bridge ? bridge.cpuUsage : 23
    property real ramUsage: bridge ? bridge.ramUsage : 45
    property real gpuUsage: bridge ? bridge.gpuUsage : 12

    Component {
        id: circularBar
        Canvas {
            width: 50
            height: 50

            property real value: 0.5
            property color barColor: theme.primary
            property string label: "CPU"

            onValueChanged: requestPaint()
            onBarColorChanged: requestPaint()

            onPaint: {
                var ctx = getContext("2d");
                ctx.reset();
                var center = Qt.point(width / 2, height / 2);
                var radius = Math.min(width, height) / 2 - 4;

                // Background
                ctx.beginPath();
                ctx.arc(center.x, center.y, radius, 0, Math.PI * 2);
                ctx.strokeStyle = theme.panelDark;
                ctx.lineWidth = 4;
                ctx.stroke();

                // Foreground
                ctx.beginPath();
                ctx.arc(center.x, center.y, radius, -Math.PI / 2, -Math.PI / 2 + value * Math.PI * 2);
                ctx.strokeStyle = barColor;
                ctx.lineWidth = 4;
                ctx.stroke();
                
                // Label
                ctx.fillStyle = theme.textSecondary;
                ctx.font = "bold 10px " + theme.fontMono;
                ctx.textAlign = "center";
                ctx.textBaseline = "middle";
                ctx.fillText(label, center.x, center.y - 5);
                
                ctx.fillStyle = theme.textPrimary;
                ctx.font = "10px " + theme.fontMono;
                ctx.fillText((value * 100).toFixed(0) + "%", center.x, center.y + 10);
            }
        }
    }

    ColumnLayout {
        anchors.fill: parent
        anchors.margins: 16
        
        Text {
            text: "SYSTEM OVERVIEW"
            font.pixelSize: 10
            color: theme.textSecondary
            font.letterSpacing: 3
            Layout.alignment: Qt.AlignHCenter
        }
        
        RowLayout {
            Layout.fillWidth: true
            
            Loader { sourceComponent: circularBar; onLoaded: { item.label = "CPU"; item.value = cpuUsage / 100; item.barColor = "#4488ff"} }
            Loader { sourceComponent: circularBar; onLoaded: { item.label = "RAM"; item.value = ramUsage / 100; item.barColor = "#44ff88"} }
            Loader { sourceComponent: circularBar; onLoaded: { item.label = "GPU"; item.value = gpuUsage / 100; item.barColor = "#ffaa44"} }
        }
    }
}
