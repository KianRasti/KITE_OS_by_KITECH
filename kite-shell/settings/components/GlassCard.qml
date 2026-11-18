import QtQuick
import QtQuick.Layouts
import "../theme"

Rectangle {
    id: card
    property string title: ""
    property string subtitle: ""
    default property alias content: innerColumn.data

    Layout.fillWidth: true
    implicitHeight: innerColumn.implicitHeight + 24
    radius: StudioTheme.cornerRadius
    color: StudioTheme.cardBackground
    border.width: 1
    border.color: StudioTheme.cardBorder

    Rectangle {
        anchors.top: parent.top
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.margins: 1
        height: 1
        color: StudioTheme.specularBorder
        opacity: 0.7
    }

    ColumnLayout {
        id: innerColumn
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.top: parent.top
        anchors.margins: 12
        spacing: 8

        Text {
            visible: card.title.length > 0
            text: card.title
            color: StudioTheme.textPrimary
            font.pixelSize: 14
            font.weight: Font.DemiBold
        }

        Text {
            visible: card.subtitle.length > 0
            text: card.subtitle
            color: StudioTheme.textSecondary
            font.pixelSize: 12
            wrapMode: Text.WordWrap
            Layout.fillWidth: true
        }
    }
}
