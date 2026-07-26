import QtQuick 2.15
import QtQuick.Controls 2.15

Item {
    id: subRoot

    property string text: ""
    onTextChanged: _render(text)

    Flickable {
        id: scrollView
        anchors.centerIn: parent
        width: parent.width
        height: Math.min(contentHeight, 220)
        contentHeight: contentItem.height
        clip: true
        interactive: contentHeight > height

        TextEdit {
            id: textDisplay
            width: scrollView.width
            textFormat: TextEdit.RichText
            color: "#e0e0e0"
            font { family: "Segoe UI"; pixelSize: 15; weight: Font.Light }
            readOnly: true
            wrapMode: Text.WordWrap
            selectByKeyboard: false
            selectByMouse: false
        }
    }

    opacity: text !== "" ? 1.0 : 0.0
    Behavior on opacity { NumberAnimation { duration: 300 } }

    function _render(md) {
        if (!md) { textDisplay.text = ""; return }

        var html = md
            .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
            .replace(/```(\w*)\n([\s\S]*?)```/g,
                '<div style="background:#0d0a08; border-left:2px solid #ff7b00; padding:8px 12px; margin:6px 0; font-family:Consolas; font-size:13px; color:#ffd700;">$2</div>')
            .replace(/`([^`]+)`/g, '<span style="background:#0d0a08; padding:1px 5px; border-radius:3px; font-family:Consolas; font-size:13px; color:#ff9500;">$1</span>')
            .replace(/\*\*(\S[^*]*\S)\*\*/g, '<b>$1</b>')
            .replace(/\*(\S[^*]*\S)\*/g, '<i>$1</i>')
            .replace(/\[([^\]]+)\]\(([^)]+)\)/g, '<a href="$2" style="color:#33aaff; text-decoration:none;">$1</a>')
            .replace(/\n/g, '<br/>')

        textDisplay.text = '<div style="text-align:center;">' + html + '</div>'
        textDisplay.cursorPosition = 0

        _animateWords(md)
    }

    property var _timers: []

    function _animateWords(fullText) {
        for (var i = 0; i < _timers.length; i++) _timers[i].stop()
        _timers = []

        textDisplay.opacity = 0.0
        var fadeTimer = Qt.createQmlObject(
            "import QtQuick 2.15; Timer { interval: 200; running: true; repeat: false }",
            subRoot, "fadeTimer"
        )
        fadeTimer.triggered.connect(function() {
            textDisplay.opacity = 1.0
        })
        _timers.push(fadeTimer)
    }
}
