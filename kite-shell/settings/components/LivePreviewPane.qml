import QtQuick
import QtQuick.Layouts
import "../theme"

Rectangle {
    id: preview
    property var settings: ({})
    property var effective: ({})

    Layout.fillWidth: true
    implicitHeight: 150
    radius: StudioTheme.cornerRadius
    clip: true
    border.width: 1
    border.color: StudioTheme.cardBorder

    gradient: Gradient {
        GradientStop { position: 0.0; color: StudioTheme.surfaceTint }
        GradientStop { position: 1.0; color: Qt.darker(StudioTheme.accentColor, 2.2) }
    }

    Rectangle {
        anchors.centerIn: parent
        anchors.verticalCenterOffset: -14
        width: 240
        height: 76
        radius: preview.effective.rounding !== undefined ? preview.effective.rounding : 12
        color: Qt.rgba(StudioTheme.surfaceTint.r, StudioTheme.surfaceTint.g, StudioTheme.surfaceTint.b, preview.settings.transparency !== undefined ? preview.settings.transparency : 0.72)
        border.width: 1
        border.color: Qt.rgba(1, 1, 1, preview.settings.specular_edge_brightness !== undefined ? preview.settings.specular_edge_brightness : 0.35)

        ColumnLayout {
            anchors.fill: parent
            anchors.margins: 10
            spacing: 4
            Text {
                text: (preview.settings.theme_preset || "Aero Blue") + " • " + (preview.effective.effective_tier || "kawase_2pass")
                color: StudioTheme.textPrimary
                font.pixelSize: 12
                font.weight: Font.Bold
            }
            Text {
                text: preview.effective.blur_enabled
                    ? ("Dual-Kawase size=" + preview.effective.blur_size + ", passes=" + preview.effective.blur_passes + ", xray=true")
                    : "Static Acrylic Fallback (0 passes)"
                color: StudioTheme.textSecondary
                font.pixelSize: 11
            }
        }
    }

    Rectangle {
        anchors.bottom: parent.bottom
        anchors.left: parent.left
        anchors.right: parent.right
        height: 30
        color: Qt.rgba(StudioTheme.surfaceTint.r, StudioTheme.surfaceTint.g, StudioTheme.surfaceTint.b, 0.85)
        border.width: 1
        border.color: StudioTheme.specularBorder

        RowLayout {
            anchors.fill: parent
            anchors.leftMargin: 10
            anchors.rightMargin: 10
            Item {
                visible: (preview.settings.taskbar_alignment || "center") === "center"
                Layout.fillWidth: true
            }
            Rectangle {
                width: 14
                height: 14
                radius: 4
                color: StudioTheme.accentColor
            }
            Rectangle {
                width: 44
                height: 14
                radius: 7
                color: Qt.rgba(1, 1, 1, 0.14)
            }
            Rectangle {
                width: 14
                height: 14
                radius: 4
                color: Qt.rgba(1, 1, 1, 0.24)
            }
            Item { Layout.fillWidth: true }
            Text {
                text: (preview.settings.taskbar_alignment || "center").toUpperCase()
                color: StudioTheme.textSecondary
                font.pixelSize: 10
            }
        }
    }
}
