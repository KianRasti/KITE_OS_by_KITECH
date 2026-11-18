import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../theme"

ColumnLayout {
    id: sliderRow
    property string label: ""
    property string valueText: ""
    property string clampHint: ""
    property real from: 0
    property real to: 1
    property real stepSize: 0.05
    property real value: 0.5

    signal committed(real newValue)

    function formattedActiveValue() {
        var v = control.pressed ? control.value : sliderRow.value
        var suffix = ""
        if (sliderRow.valueText.endsWith("px")) suffix = "px"
        else if (sliderRow.valueText.endsWith("x")) suffix = "x"
        if (sliderRow.stepSize >= 1) {
            return Math.round(v) + suffix
        }
        return Number(v).toFixed(2) + suffix
    }

    Layout.fillWidth: true
    spacing: 4

    RowLayout {
        Layout.fillWidth: true
        Text {
            text: sliderRow.label
            color: StudioTheme.textPrimary
            font.pixelSize: 13
            Layout.fillWidth: true
        }
        Text {
            visible: sliderRow.clampHint.length > 0
            text: sliderRow.clampHint
            color: StudioTheme.warningAmber
            font.pixelSize: 11
            font.weight: Font.DemiBold
        }
        Text {
            text: control.pressed
                ? sliderRow.formattedActiveValue()
                : (sliderRow.valueText.length > 0 ? sliderRow.valueText : String(sliderRow.value))
            color: StudioTheme.accentColor
            font.pixelSize: 12
            font.weight: Font.Bold
        }
    }

    Slider {
        id: control
        Layout.fillWidth: true
        from: sliderRow.from
        to: sliderRow.to
        stepSize: sliderRow.stepSize
        Component.onCompleted: control.value = sliderRow.value
        onPressedChanged: {
            if (!pressed) {
                sliderRow.committed(value)
            }
        }
    }

    Connections {
        target: sliderRow
        function onValueChanged() {
            if (!control.pressed) {
                control.value = sliderRow.value
            }
        }
    }
}
