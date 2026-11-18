pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import Quickshell
import Quickshell.Io
import Quickshell.Wayland
import "components"

PanelWindow {
    id: startWindow
    required property ShellState shellState

    visible: shellState.startMenuOpen
    anchors {
        bottom: true
        left: shellState.taskbarAlignment === "left"
    }
    margins {
        bottom: 58
        left: shellState.taskbarAlignment === "left" ? 12 : 0
    }

    implicitWidth: 620
    implicitHeight: 620
    color: "transparent"
    WlrLayershell.namespace: "quickshell"
    WlrLayershell.keyboardFocus: WlrKeyboardFocus.OnDemand

    property string searchQuery: ""
    property string platformFilter: "all"
    property bool showAllApps: false
    property bool powerMenuOpen: false
    property var fileResults: []
    property var aiSpotlightCards: []
    property string aiTierBadge: "Tier 0 (0 tokens)"

    onVisibleChanged: {
        if (visible) {
            searchInput.forceActiveFocus()
            powerMenuOpen = false
        }
    }

    function filteredEntries() {
        var list = DesktopEntries.applications.values || []
        var q = searchQuery.trim().toLowerCase()
        var out = []
        for (var i = 0; i < list.length; i++) {
            var e = list[i]
            var plat = shellState.resolvePlatform(e)
            if (platformFilter !== "all" && plat !== platformFilter) continue
            var nameStr = String(e.name || "").toLowerCase()
            var tagStr = shellState.platformTagText(plat).toLowerCase()
            if (q && nameStr.indexOf(q) === -1 && tagStr.indexOf(q) === -1) continue
            out.push({ entry: e, platform: plat })
        }
        return out
    }

    Process {
        id: fileFinder
        stdout: StdioCollector {
            onStreamFinished: {
                try {
                    var parsed = JSON.parse(this.text || "{}")
                    var cards = []
                    if (parsed.groups) {
                        for (var g = 0; g < parsed.groups.length; g++) {
                            var grp = parsed.groups[g]
                            for (var j = 0; j < grp.items.length; j++) {
                                cards.push(grp.items[j])
                            }
                        }
                    }
                    startWindow.aiSpotlightCards = cards.slice(0, 8)
                    startWindow.aiTierBadge = (parsed.tier === "tier1_cloud") ? ("BYOK (" + parsed.tokens_used + " tok)") : "Tier 0 (0 tokens)"
                } catch (err) {
                    var lines = (this.text || "").split("\n").filter(function(l) { return l.trim().length > 0 })
                    startWindow.fileResults = lines.slice(0, 6)
                }
            }
        }
    }

    GlassPanel {
        anchors.fill: parent
        shellState: startWindow.shellState

        ColumnLayout {
            anchors.fill: parent
            anchors.margins: 16
            spacing: 12

            // Universal AI Spotlight Search Box
            TextField {
                id: searchInput
                Layout.fillWidth: true
                placeholderText: "Ask Kite AI or search files, [Win]/[Android]/[macOS] tags..."
                onTextChanged: {
                    startWindow.searchQuery = text
                    if (text.trim().length >= 2) {
                        fileFinder.command = ["kite-ai", "query", text.trim()]
                        fileFinder.running = true
                    } else {
                        startWindow.fileResults = []
                        startWindow.aiSpotlightCards = []
                    }
                }
            }

            // Platform Filter Chips
            RowLayout {
                Layout.fillWidth: true
                spacing: 6

                Repeater {
                    model: [
                        { key: "all", label: "All" },
                        { key: "linux", label: "Linux" },
                        { key: "win", label: "[Win]" },
                        { key: "android", label: "[Android]" },
                        { key: "macos", label: "[macOS]" }
                    ]
                    delegate: Button {
                        required property var modelData
                        text: modelData.label
                        highlighted: startWindow.platformFilter === modelData.key
                        onClicked: startWindow.platformFilter = modelData.key
                    }
                }

                Item { Layout.fillWidth: true }

                Button {
                    text: startWindow.showAllApps ? "Pinned" : "All apps >"
                    onClicked: startWindow.showAllApps = !startWindow.showAllApps
                }
            }

            // Apps Grid / List
            GridView {
                id: appsGrid
                Layout.fillWidth: true
                Layout.fillHeight: true
                clip: true
                cellWidth: startWindow.showAllApps ? width : 140
                cellHeight: startWindow.showAllApps ? 46 : 96
                model: startWindow.filteredEntries()

                delegate: Rectangle {
                    required property var modelData
                    width: appsGrid.cellWidth - 6
                    height: appsGrid.cellHeight - 6
                    radius: 10
                    color: itemMouse.containsMouse ? Qt.rgba(1, 1, 1, 0.14) : Qt.rgba(1, 1, 1, 0.05)

                    ColumnLayout {
                        anchors.fill: parent
                        anchors.margins: 8
                        spacing: 4

                        RowLayout {
                            Layout.fillWidth: true
                            AppIcon {
                                iconName: modelData.entry.icon || ""
                                fallbackLabel: modelData.entry.name || "A"
                            }
                            Item { Layout.fillWidth: true }
                            PlatformBadge {
                                platform: modelData.platform
                            }
                        }

                        Text {
                            text: modelData.entry.name || "App"
                            color: "#F8FAFC"
                            font.pixelSize: 12
                            elide: Text.ElideRight
                            Layout.fillWidth: true
                        }
                    }

                    MouseArea {
                        id: itemMouse
                        anchors.fill: parent
                        hoverEnabled: true
                        cursorShape: Qt.PointingHandCursor
                        onClicked: {
                            startWindow.shellState.closeOverlays()
                            if (modelData.entry && modelData.entry.execute) {
                                modelData.entry.execute()
                            }
                        }
                    }
                }
            }

            // Local Files & Web Search Results Row
            ColumnLayout {
                visible: startWindow.searchQuery.trim().length >= 2
                Layout.fillWidth: true
                spacing: 4

                Repeater {
                    model: startWindow.fileResults
                    delegate: Text {
                        required property string modelData
                        text: "File: " + modelData
                        color: "#94A3B8"
                        font.pixelSize: 11
                        elide: Text.ElideMiddle
                        Layout.fillWidth: true
                    }
                }
            }

            // Footer: User + Settings + Power Menu
            RowLayout {
                Layout.fillWidth: true
                spacing: 8

                Text {
                    text: Quickshell.env("USER") || "kite"
                    color: "#E2E8F0"
                    font.pixelSize: 12
                    font.weight: Font.DemiBold
                    Layout.fillWidth: true
                }

                Button {
                    text: "Settings"
                    onClicked: startWindow.shellState.openSettings()
                }

                Button {
                    text: "Power"
                    onClicked: startWindow.powerMenuOpen = !startWindow.powerMenuOpen
                }
            }

            // Power Options Drawer (Sleep / Hibernate / Restart / Shutdown / Lock)
            RowLayout {
                visible: startWindow.powerMenuOpen
                Layout.fillWidth: true
                spacing: 6

                Button {
                    text: "Lock"
                    onClicked: startWindow.shellState.launchCommand("loginctl lock-session")
                }
                Button {
                    text: "Sleep"
                    onClicked: startWindow.shellState.launchCommand("systemctl suspend")
                }
                Button {
                    text: "Hibernate"
                    onClicked: startWindow.shellState.launchCommand("systemctl hibernate")
                }
                Button {
                    text: "Restart"
                    onClicked: startWindow.shellState.launchCommand("systemctl reboot")
                }
                Button {
                    text: "Shutdown"
                    onClicked: startWindow.shellState.launchCommand("systemctl poweroff")
                }
            }
        }
    }
}
