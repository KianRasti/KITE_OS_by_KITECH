pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import Quickshell
import Quickshell.Wayland
import "components"

PanelWindow {
    id: snapWindow
    required property ShellState shellState

    visible: shellState.snapLayoutsOpen
    anchors {
        top: true
        right: true
    }
    margins {
        top: 48
        right: 24
    }

    implicitWidth: Math.min(420, Math.max(320, (screen ? screen.width : 1280) - 24))
    implicitHeight: Math.min(250, Math.max(200, (screen ? screen.height : 720) - 96))
    color: "transparent"
    WlrLayershell.namespace: "quickshell"
    WlrLayershell.keyboardFocus: WlrKeyboardFocus.OnDemand

    GlassPanel {
        anchors.fill: parent
        shellState: snapWindow.shellState

        ColumnLayout {
            anchors.fill: parent
            anchors.margins: 14
            spacing: 10

            Text {
                text: "Snap Layouts (Win+Z)"
                color: "#F8FAFC"
                font.pixelSize: 14
                font.weight: Font.Bold
            }

            GridLayout {
                Layout.fillWidth: true
                Layout.fillHeight: true
                columns: 2
                columnSpacing: 10
                rowSpacing: 10

                // 1. Halves (50/50)
                Rectangle {
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    radius: 8
                    color: Qt.rgba(1, 1, 1, 0.06)
                    RowLayout {
                        anchors.fill: parent
                        anchors.margins: 8
                        spacing: 6
                        Button {
                            Layout.fillWidth: true
                            Layout.fillHeight: true
                            text: "Left 50%"
                            onClicked: snapWindow.shellState.snapActiveWindow("left-half", snapWindow.screen.width, snapWindow.screen.height)
                        }
                        Button {
                            Layout.fillWidth: true
                            Layout.fillHeight: true
                            text: "Right 50%"
                            onClicked: snapWindow.shellState.snapActiveWindow("right-half", snapWindow.screen.width, snapWindow.screen.height)
                        }
                    }
                }

                // 2. 60/40 Split
                Rectangle {
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    radius: 8
                    color: Qt.rgba(1, 1, 1, 0.06)
                    RowLayout {
                        anchors.fill: parent
                        anchors.margins: 8
                        spacing: 6
                        Button {
                            Layout.fillWidth: true
                            Layout.preferredWidth: 60
                            Layout.fillHeight: true
                            text: "60%"
                            onClicked: snapWindow.shellState.snapActiveWindow("split-60", snapWindow.screen.width, snapWindow.screen.height)
                        }
                        Button {
                            Layout.fillWidth: true
                            Layout.preferredWidth: 40
                            Layout.fillHeight: true
                            text: "40%"
                            onClicked: snapWindow.shellState.snapActiveWindow("split-40", snapWindow.screen.width, snapWindow.screen.height)
                        }
                    }
                }

                // 3. Quarters
                Rectangle {
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    Layout.columnSpan: 2
                    radius: 8
                    color: Qt.rgba(1, 1, 1, 0.06)
                    GridLayout {
                        anchors.fill: parent
                        anchors.margins: 8
                        columns: 2
                        columnSpacing: 6
                        rowSpacing: 6
                        Button {
                            Layout.fillWidth: true
                            Layout.fillHeight: true
                            text: "Top-Left Quarter"
                            onClicked: snapWindow.shellState.snapActiveWindow("top-left", snapWindow.screen.width, snapWindow.screen.height)
                        }
                        Button {
                            Layout.fillWidth: true
                            Layout.fillHeight: true
                            text: "Top-Right Quarter"
                            onClicked: snapWindow.shellState.snapActiveWindow("top-right", snapWindow.screen.width, snapWindow.screen.height)
                        }
                        Button {
                            Layout.fillWidth: true
                            Layout.fillHeight: true
                            text: "Bottom-Left Quarter"
                            onClicked: snapWindow.shellState.snapActiveWindow("bottom-left", snapWindow.screen.width, snapWindow.screen.height)
                        }
                        Button {
                            Layout.fillWidth: true
                            Layout.fillHeight: true
                            text: "Bottom-Right Quarter"
                            onClicked: snapWindow.shellState.snapActiveWindow("bottom-right", snapWindow.screen.width, snapWindow.screen.height)
                        }
                    }
                }
            }
        }
    }
}
