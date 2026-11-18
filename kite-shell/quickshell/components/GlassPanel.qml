import QtQuick

Rectangle {
    id: panel
    required property var shellState
    property int panelRadius: shellState ? shellState.cornerRadius : 12

    radius: panelRadius
    color: {
        var tint = shellState ? shellState.surfaceTint : Qt.color("#0F172A")
        var alpha = shellState ? shellState.effectiveOpacity : 0.72
        return Qt.rgba(tint.r, tint.g, tint.b, alpha)
    }
    border.width: 1
    border.color: Qt.rgba(1, 1, 1, shellState ? shellState.specularEdgeBrightness : 0.35)

    Rectangle {
        anchors.top: parent.top
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.margins: 1
        height: 1
        color: Qt.rgba(1, 1, 1, shellState ? Math.min(1.0, shellState.specularEdgeBrightness * 1.4) : 0.45)
    }
}
