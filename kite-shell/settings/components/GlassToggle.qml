import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../theme"

RowLayout {
    id: toggleRow
    property string label: ""
    property string subtitle: ""
    property bool checked: false

    signal toggledRequested(bool nextValue)

    Layout.fillWidth: true
    spacing: 10

    ColumnLayout {
        Layout.fillWidth: true
        spacing: 2
        Text {
            text: toggleRow.label
            color: StudioTheme.textPrimary
            font.pixelSize: 13
            font.weight: Font.Medium
        }
        Text {
            visible: toggleRow.subtitle.length > 0
            text: toggleRow.subtitle
            color: StudioTheme.textSecondary
            font.pixelSize: 11
            wrapMode: Text.WordWrap
            Layout.fillWidth: true
        }
    }

    Switch {
        checked: toggleRow.checked
        onClicked: toggleRow.toggledRequested(!toggleRow.checked)
    }
}
