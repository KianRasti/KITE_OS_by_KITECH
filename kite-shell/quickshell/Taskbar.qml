pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Layouts
import Quickshell
import Quickshell.Wayland
import Quickshell.Hyprland
import Quickshell.Services.SystemTray
import "components"

PanelWindow {
    id: taskbarWindow
    required property ShellState shellState

    anchors {
        bottom: true
        left: true
        right: true
    }

    implicitHeight: 48
    exclusiveZone: 48
    color: "transparent"
    WlrLayershell.namespace: "quickshell"

    property string clockTime: Qt.formatTime(new Date(), "hh:mm")
    property string clockDate: Qt.formatDate(new Date(), "yyyy-MM-dd")

    Timer {
        interval: 15000
        running: true
        repeat: true
        onTriggered: {
            var now = new Date()
            taskbarWindow.clockTime = Qt.formatTime(now, "hh:mm")
            taskbarWindow.clockDate = Qt.formatDate(now, "yyyy-MM-dd")
        }
    }

    GlassPanel {
        anchors.fill: parent
        anchors.leftMargin: 6
        anchors.rightMargin: 6
        anchors.bottomMargin: 4
        shellState: taskbarWindow.shellState
        panelRadius: Math.min(12, taskbarWindow.shellState.cornerRadius)

        RowLayout {
            anchors.fill: parent
            anchors.leftMargin: 10
            anchors.rightMargin: 10
            spacing: 8

            Item {
                visible: taskbarWindow.shellState.taskbarAlignment === "center"
                Layout.fillWidth: true
            }

            // Start Button
            Rectangle {
                implicitWidth: 34
                implicitHeight: 34
                radius: 8
                color: taskbarWindow.shellState.startMenuOpen
                    ? Qt.rgba(1, 1, 1, 0.22)
                    : (startHover.containsMouse ? Qt.rgba(1, 1, 1, 0.12) : "transparent")
                border.width: taskbarWindow.shellState.startMenuOpen ? 1 : 0
                border.color: taskbarWindow.shellState.accentColor

                Text {
                    anchors.centerIn: parent
                    text: "❖"
                    color: taskbarWindow.shellState.accentColor
                    font.pixelSize: 18
                }

                MouseArea {
                    id: startHover
                    anchors.fill: parent
                    hoverEnabled: true
                    cursorShape: Qt.PointingHandCursor
                    onClicked: taskbarWindow.shellState.toggleOverlay("start")
                }
            }

            // AI Spotlight Search Pill (Win+S)
            Rectangle {
                implicitWidth: 236
                implicitHeight: 32
                radius: 16
                color: Qt.rgba(1, 1, 1, 0.11)
                border.width: 1
                border.color: Qt.rgba(1, 1, 1, 0.22)

                RowLayout {
                    anchors.fill: parent
                    anchors.leftMargin: 12
                    anchors.rightMargin: 12
                    spacing: 6
                    Text {
                        text: "Ask Kite AI or search files... (Win+S)"
                        color: "#CBD5E1"
                        font.pixelSize: 11
                        elide: Text.ElideRight
                        Layout.fillWidth: true
                    }
                }

                MouseArea {
                    anchors.fill: parent
                    cursorShape: Qt.PointingHandCursor
                    onClicked: taskbarWindow.shellState.toggleOverlay("start")
                }
            }

            // Running Hyprland Toplevels with 24px icon, corner badge & morphing active pill
            RowLayout {
                spacing: 6
                Repeater {
                    model: Hyprland.toplevels
                    delegate: Rectangle {
                        required property var modelData
                        implicitHeight: 36
                        implicitWidth: 44
                        radius: 9
                        color: modelData.activated ? Qt.rgba(1, 1, 1, 0.22) : Qt.rgba(1, 1, 1, 0.08)
                        border.width: modelData.activated ? 1 : 0
                        border.color: taskbarWindow.shellState.accentColor

                        AppIcon {
                            anchors.centerIn: parent
                            width: 24
                            height: 24
                            iconName: modelData.title || ""
                            fallbackLabel: modelData.title || "A"
                        }

                        PlatformBadge {
                            anchors.top: parent.top
                            anchors.right: parent.right
                            anchors.margins: 2
                            platform: {
                                var c = String(modelData.lastIpcObject ? modelData.lastIpcObject.class : "")
                                if (c.indexOf("wine") !== -1 || c.indexOf(".exe") !== -1) return "win"
                                if (c.indexOf("Waydroid") !== -1 || c.indexOf("waydroid") !== -1) return "android"
                                if (c.indexOf("macos") !== -1 || c.indexOf("qemu") !== -1) return "macos"
                                return "linux"
                            }
                        }

                        // Width-morphing active bottom indicator pill
                        Rectangle {
                            anchors.bottom: parent.bottom
                            anchors.bottomMargin: 2
                            anchors.horizontalCenter: parent.horizontalCenter
                            height: 3
                            radius: 2
                            implicitWidth: modelData.activated ? 16 : 6
                            color: modelData.activated ? taskbarWindow.shellState.accentColor : "#94A3B8"
                            Behavior on implicitWidth {
                                NumberAnimation { duration: 180; easing.type: Easing.OutCubic }
                            }
                        }

                        MouseArea {
                            anchors.fill: parent
                            cursorShape: Qt.PointingHandCursor
                            onClicked: Hyprland.dispatch("focuswindow address:" + modelData.address)
                        }
                    }
                }
            }

            Item {
                Layout.fillWidth: true
            }

            // Alignment Toggle Pill (Center <-> Left)
            Rectangle {
                implicitWidth: 52
                implicitHeight: 28
                radius: 8
                color: Qt.rgba(1, 1, 1, 0.09)
                Text {
                    anchors.centerIn: parent
                    text: taskbarWindow.shellState.taskbarAlignment === "center" ? "CTR" : "LFT"
                    color: "#CBD5E1"
                    font.pixelSize: 10
                    font.weight: Font.Bold
                }
                MouseArea {
                    anchors.fill: parent
                    cursorShape: Qt.PointingHandCursor
                    onClicked: taskbarWindow.shellState.toggleTaskbarAlignment()
                }
            }

            // SystemTray items
            RowLayout {
                spacing: 4
                Repeater {
                    model: SystemTray.items
                    delegate: Rectangle {
                        required property var modelData
                        implicitWidth: 24
                        implicitHeight: 24
                        radius: 6
                        color: Qt.rgba(1, 1, 1, 0.06)
                        Image {
                            anchors.centerIn: parent
                            width: 16
                            height: 16
                            source: modelData.icon || ""
                        }
                        MouseArea {
                            anchors.fill: parent
                            acceptedButtons: Qt.LeftButton | Qt.RightButton
                            onClicked: function(mouse) {
                                if (mouse.button === Qt.RightButton) modelData.secondaryActivate()
                                else modelData.activate()
                            }
                        }
                    }
                }
            }

            // Quick Settings Cluster (Win+A)
            Rectangle {
                implicitWidth: 74
                implicitHeight: 32
                radius: 8
                color: taskbarWindow.shellState.quickSettingsOpen
                    ? Qt.rgba(1, 1, 1, 0.20)
                    : Qt.rgba(1, 1, 1, 0.08)

                RowLayout {
                    anchors.centerIn: parent
                    spacing: 6
                    Text { text: "WiFi"; color: "#E2E8F0"; font.pixelSize: 10 }
                    Text { text: taskbarWindow.shellState.powerSource === "AC" ? "AC" : "BAT"; color: taskbarWindow.shellState.accentColor; font.pixelSize: 10; font.weight: Font.Bold }
                }

                MouseArea {
                    anchors.fill: parent
                    cursorShape: Qt.PointingHandCursor
                    onClicked: taskbarWindow.shellState.toggleOverlay("quickSettings")
                }
            }

            // Date / Time & Notifications Pill (Win+N)
            Rectangle {
                implicitWidth: 94
                implicitHeight: 34
                radius: 8
                color: taskbarWindow.shellState.notificationsOpen
                    ? Qt.rgba(1, 1, 1, 0.20)
                    : Qt.rgba(1, 1, 1, 0.08)

                ColumnLayout {
                    anchors.centerIn: parent
                    spacing: 0
                    Text {
                        Layout.alignment: Qt.AlignHCenter
                        text: taskbarWindow.clockTime
                        color: "#F8FAFC"
                        font.pixelSize: 11
                        font.weight: Font.DemiBold
                    }
                    Text {
                        Layout.alignment: Qt.AlignHCenter
                        text: taskbarWindow.clockDate
                        color: "#94A3B8"
                        font.pixelSize: 9
                    }
                }

                MouseArea {
                    anchors.fill: parent
                    cursorShape: Qt.PointingHandCursor
                    onClicked: taskbarWindow.shellState.toggleOverlay("notifications")
                }
            }
        }
    }
}
