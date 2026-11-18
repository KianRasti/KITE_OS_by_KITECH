import QtQuick
import QtQuick.Layouts
import "../theme"

Rectangle {
    id: swatch
    property string presetName: ""
    property string accentColor: "#38BDF8"
    property string surfaceTint: "#0F172A"
    property real transparency: 0.72
    property int blurRadius: 6
    property bool selected: false

    signal clicked()

    implicitWidth: 136
    implicitHeight: 74
    radius: 10
    color: surfaceTint
    border.width: selected ? 2 : 1
    border.color: selected ? accentColor : StudioTheme.cardBorder

    ColumnLayout {
        anchors.fill: parent
        anchors.margins: 8
        spacing: 4

        RowLayout {
            Layout.fillWidth: true
            Rectangle {
                width: 16
                height: 16
                radius: 8
                color: swatch.accentColor
            }
            Item { Layout.fillWidth: true }
            Text {
                text: swatch.blurRadius > 0 ? (swatch.blurRadius + "px") : "Flat"
                color: StudioTheme.textSecondary
                font.pixelSize: 10
            }
        }

        Item { Layout.fillHeight: true }

        Text {
            text: swatch.presetName
            color: StudioTheme.textPrimary
            font.pixelSize: 12
            font.weight: swatch.selected ? Font.Bold : Font.Medium
            elide: Text.ElideRight
            Layout.fillWidth: true
        }
    }

    MouseArea {
        anchors.fill: parent
        cursorShape: Qt.PointingHandCursor
        onClicked: swatch.clicked()
    }
}
