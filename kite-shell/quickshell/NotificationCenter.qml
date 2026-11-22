pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import Quickshell
import Quickshell.Wayland
import Quickshell.Services.Notifications
import "components"

PanelWindow {
    id: notifWindow
    required property ShellState shellState

    visible: shellState.notificationsOpen
    anchors {
        bottom: true
        right: true
    }
    margins {
        bottom: 58
        right: 12
    }

    implicitWidth: Math.min(360, Math.max(300, (screen ? screen.width : 1280) - 24))
    implicitHeight: Math.min(480, Math.max(320, (screen ? screen.height : 720) - 72))
    color: "transparent"
    WlrLayershell.namespace: "quickshell"
    WlrLayershell.keyboardFocus: WlrKeyboardFocus.OnDemand

    property bool doNotDisturb: false
    property int calYear: (new Date()).getFullYear()
    property int calMonth: (new Date()).getMonth()
    property int selectedDay: (new Date()).getDate()

    ListModel {
        id: notificationsModel
    }

    NotificationServer {
        id: notificationServer
        onNotification: function(notification) {
            if (notifWindow.doNotDisturb) return
            var app = String(notification.appName || "System")
            var isAndroid = app.toLowerCase().indexOf("waydroid") !== -1 || app.toLowerCase().indexOf("android") !== -1
            notificationsModel.insert(0, {
                appName: app,
                summary: String(notification.summary || ""),
                body: String(notification.body || ""),
                platform: isAndroid ? "android" : "linux"
            })
        }
    }

    function calendarDays(year, month) {
        var first = new Date(year, month, 1)
        var offset = first.getDay()
        var daysInMonth = new Date(year, month + 1, 0).getDate()
        var cells = []
        for (var i = 0; i < offset; i++) cells.push("")
        for (var d = 1; d <= daysInMonth; d++) cells.push(String(d))
        return cells
    }

    GlassPanel {
        anchors.fill: parent
        shellState: notifWindow.shellState

        ColumnLayout {
            anchors.fill: parent
            anchors.margins: 14
            spacing: 10

            RowLayout {
                Layout.fillWidth: true
                Text {
                    text: "Notifications"
                    color: "#F8FAFC"
                    font.pixelSize: 15
                    font.weight: Font.Bold
                    Layout.fillWidth: true
                }
                Button {
                    text: notifWindow.doNotDisturb ? "DND: On" : "DND: Off"
                    onClicked: notifWindow.doNotDisturb = !notifWindow.doNotDisturb
                }
                Button {
                    text: "Clear all"
                    onClicked: notificationsModel.clear()
                }
            }

            ListView {
                Layout.fillWidth: true
                Layout.fillHeight: true
                clip: true
                spacing: 6
                model: notificationsModel
                delegate: Rectangle {
                    id: notifCard
                    required property int index
                    required property string appName
                    required property string summary
                    required property string body
                    required property string platform

                    width: ListView.view.width
                    implicitHeight: contentCol.implicitHeight + 16
                    radius: 8
                    color: Qt.rgba(1, 1, 1, 0.08)

                    ColumnLayout {
                        id: contentCol
                        anchors.fill: parent
                        anchors.margins: 8
                        spacing: 2

                        RowLayout {
                            Layout.fillWidth: true
                            PlatformBadge { platform: notifCard.platform }
                            Text {
                                text: appName
                                color: "#94A3B8"
                                font.pixelSize: 11
                                Layout.fillWidth: true
                            }
                            Button {
                                text: "x"
                                onClicked: notificationsModel.remove(index)
                            }
                        }

                        Text {
                            text: summary
                            color: "#F8FAFC"
                            font.pixelSize: 12
                            font.weight: Font.Bold
                        }

                        Text {
                            text: body
                            color: "#CBD5E1"
                            font.pixelSize: 11
                            wrapMode: Text.WordWrap
                            Layout.fillWidth: true
                        }
                    }
                }
            }

            // Interactive Calendar
            Rectangle {
                Layout.fillWidth: true
                implicitHeight: 210
                radius: 10
                color: Qt.rgba(0, 0, 0, 0.25)

                ColumnLayout {
                    anchors.fill: parent
                    anchors.margins: 10
                    spacing: 6

                    RowLayout {
                        Layout.fillWidth: true
                        Button {
                            text: "<"
                            onClicked: {
                                if (notifWindow.calMonth === 0) {
                                    notifWindow.calMonth = 11
                                    notifWindow.calYear -= 1
                                } else {
                                    notifWindow.calMonth -= 1
                                }
                            }
                        }
                        Text {
                            Layout.fillWidth: true
                            horizontalAlignment: Text.AlignHCenter
                            text: Qt.formatDate(new Date(notifWindow.calYear, notifWindow.calMonth, 1), "MMMM yyyy")
                            color: "#F8FAFC"
                            font.pixelSize: 13
                            font.weight: Font.DemiBold
                        }
                        Button {
                            text: ">"
                            onClicked: {
                                if (notifWindow.calMonth === 11) {
                                    notifWindow.calMonth = 0
                                    notifWindow.calYear += 1
                                } else {
                                    notifWindow.calMonth += 1
                                }
                            }
                        }
                    }

                    GridLayout {
                        Layout.fillWidth: true
                        Layout.fillHeight: true
                        columns: 7
                        columnSpacing: 4
                        rowSpacing: 4

                        Repeater {
                            model: notifWindow.calendarDays(notifWindow.calYear, notifWindow.calMonth)
                            delegate: Rectangle {
                                required property string modelData
                                Layout.fillWidth: true
                                Layout.fillHeight: true
                                radius: 6
                                color: modelData === String(notifWindow.selectedDay)
                                    ? notifWindow.shellState.accentColor
                                    : "transparent"

                                Text {
                                    anchors.centerIn: parent
                                    text: modelData
                                    color: modelData === String(notifWindow.selectedDay) ? "#0F172A" : "#E2E8F0"
                                    font.pixelSize: 11
                                }

                                MouseArea {
                                    anchors.fill: parent
                                    enabled: modelData.length > 0
                                    onClicked: notifWindow.selectedDay = parseInt(modelData, 10)
                                }
                            }
                        }
                    }
                }
            }
        }
    }
}
