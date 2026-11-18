import QtQuick
import QtQuick.Layouts
import "../theme"

Rectangle {
    id: banner
    property string message: ""
    property bool severe: false

    Layout.fillWidth: true
    implicitHeight: textItem.implicitHeight + 20
    radius: 8
    color: severe ? Qt.rgba(0.94, 0.27, 0.27, 0.18) : Qt.rgba(0.96, 0.62, 0.04, 0.16)
    border.width: 1
    border.color: severe ? StudioTheme.dangerRed : StudioTheme.warningAmber

    Text {
        id: textItem
        anchors.fill: parent
        anchors.margins: 10
        text: banner.message
        color: StudioTheme.textPrimary
        font.pixelSize: 12
        wrapMode: Text.WordWrap
    }
}
