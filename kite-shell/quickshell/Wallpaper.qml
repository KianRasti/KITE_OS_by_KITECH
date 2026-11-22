pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Layouts
import Quickshell
import Quickshell.Wayland

PanelWindow {
    id: wallpaperWindow
    required property ShellState shellState

    anchors {
        top: true
        bottom: true
        left: true
        right: true
    }

    WlrLayershell.layer: WlrLayer.Background
    WlrLayershell.namespace: "kite-wallpaper"
    WlrLayershell.exclusionMode: ExclusionMode.Ignore
    color: "#060B16"

    Rectangle {
        anchors.fill: parent
        gradient: Gradient {
            orientation: Gradient.Vertical
            GradientStop { position: 0.0; color: "#071124" }
            GradientStop { position: 0.48; color: "#0B1933" }
            GradientStop { position: 1.0; color: "#060B16" }
        }

        // Ambient Aero Blue Glass Glow Orbs (pure QtQuick, zero GPU shader overhead)
        Rectangle {
            width: Math.min(parent.width * 0.65, 760)
            height: width
            radius: width / 2
            anchors.horizontalCenter: parent.horizontalCenter
            anchors.verticalCenter: parent.verticalCenter
            anchors.verticalCenterOffset: -parent.height * 0.08
            color: Qt.rgba(0.22, 0.74, 0.97, 0.11)
        }

        Rectangle {
            width: Math.min(parent.width * 0.42, 480)
            height: width
            radius: width / 2
            anchors.right: parent.right
            anchors.top: parent.top
            anchors.rightMargin: -width * 0.25
            anchors.topMargin: -width * 0.25
            color: Qt.rgba(0.05, 0.65, 0.91, 0.09)
        }

        Rectangle {
            width: Math.min(parent.width * 0.38, 420)
            height: width
            radius: width / 2
            anchors.left: parent.left
            anchors.bottom: parent.bottom
            anchors.leftMargin: -width * 0.18
            anchors.bottomMargin: -width * 0.12
            color: Qt.rgba(0.38, 0.65, 0.98, 0.08)
        }

        // Subtle KITech Desktop Watermark (bottom-right above taskbar)
        ColumnLayout {
            anchors.right: parent.right
            anchors.bottom: parent.bottom
            anchors.rightMargin: 24
            anchors.bottomMargin: 64
            spacing: 2

            Text {
                text: "KITE_OS™"
                color: Qt.rgba(0.88, 0.95, 1.0, 0.28)
                font.pixelSize: 15
                font.weight: Font.DemiBold
                Layout.alignment: Qt.AlignRight
            }

            Text {
                text: "Built by KITech  •  kian.kitech.info"
                color: Qt.rgba(0.58, 0.72, 0.86, 0.22)
                font.pixelSize: 11
                Layout.alignment: Qt.AlignRight
            }
        }
    }
}
