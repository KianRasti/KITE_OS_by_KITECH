pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../theme"

Rectangle {
    id: sidebarRoot
    property int currentIndex: 3
    property string searchFilter: ""
    property var hwProfile: ({})
    property var effectiveConfig: ({})

    signal categorySelected(int index)
    signal searchChanged(string query)

    readonly property var categories: [
        { origIndex: 0, id: "system", title: "System", tag: "SYS", keywords: "display btrfs pipewire audio" },
        { origIndex: 1, id: "bluetooth", title: "Bluetooth & devices", tag: "BT", keywords: "wifi 7260 synaptics fingerprint" },
        { origIndex: 2, id: "network", title: "Network & internet", tag: "NET", keywords: "iwlwifi e1000e ethernet" },
        { origIndex: 3, id: "personalization", title: "Personalization", tag: "FX", keywords: "glass blur preset accent wallpaper taskbar spring transparency" },
        { origIndex: 4, id: "apps", title: "Apps & KiteBridge", tag: "APP", keywords: "wine dxvk waydroid android macos darling" },
        { origIndex: 5, id: "performance", title: "Performance & Hardware", tag: "HW", keywords: "ram 4g 8g 16g battery zram mitigations" },
        { origIndex: 6, id: "accounts", title: "Accounts", tag: "USR", keywords: "user folders desktop documents" },
        { origIndex: 7, id: "update", title: "System Update", tag: "UPD", keywords: "cachyos arch snapshot" },
        { origIndex: 8, id: "ai-indexing", title: "AI & Indexing", tag: "AI", keywords: "kite ai spotlight byok token budget kiteignore fts5" }
    ]

    readonly property var filteredCategories: {
        var q = String(searchFilter || "").trim().toLowerCase()
        if (!q) return categories
        var out = []
        for (var i = 0; i < categories.length; i++) {
            var c = categories[i]
            if (c.title.toLowerCase().indexOf(q) !== -1 ||
                c.tag.toLowerCase().indexOf(q) !== -1 ||
                c.keywords.indexOf(q) !== -1) {
                out.push(c)
            }
        }
        return out
    }

    radius: StudioTheme.cornerRadius
    color: StudioTheme.cardBackground
    border.width: 1
    border.color: StudioTheme.cardBorder

    ColumnLayout {
        anchors.fill: parent
        anchors.margins: 10
        spacing: 8

        Text {
            text: "KITE_OS Studio"
            color: StudioTheme.textPrimary
            font.pixelSize: 15
            font.weight: Font.Bold
        }

        TextField {
            id: searchBox
            Layout.fillWidth: true
            placeholderText: "Find a setting"
            onTextChanged: sidebarRoot.searchChanged(text)
        }

        ListView {
            Layout.fillWidth: true
            Layout.fillHeight: true
            clip: true
            spacing: 4
            model: sidebarRoot.filteredCategories

            delegate: Rectangle {
                required property int index
                required property var modelData

                width: ListView.view.width
                height: 36
                radius: 8
                color: modelData.origIndex === sidebarRoot.currentIndex
                    ? Qt.rgba(StudioTheme.accentColor.r, StudioTheme.accentColor.g, StudioTheme.accentColor.b, 0.22)
                    : (hoverArea.containsMouse ? Qt.rgba(1, 1, 1, 0.07) : "transparent")
                border.width: modelData.origIndex === sidebarRoot.currentIndex ? 1 : 0
                border.color: StudioTheme.accentColor

                RowLayout {
                    anchors.fill: parent
                    anchors.leftMargin: 10
                    anchors.rightMargin: 10
                    spacing: 8

                    Text {
                        text: modelData.tag
                        color: modelData.origIndex === sidebarRoot.currentIndex ? StudioTheme.accentColor : StudioTheme.textSecondary
                        font.pixelSize: 10
                        font.weight: Font.Bold
                    }

                    Text {
                        text: modelData.title
                        color: StudioTheme.textPrimary
                        font.pixelSize: 13
                        elide: Text.ElideRight
                        Layout.fillWidth: true
                    }
                }

                MouseArea {
                    id: hoverArea
                    anchors.fill: parent
                    hoverEnabled: true
                    cursorShape: Qt.PointingHandCursor
                    onClicked: sidebarRoot.categorySelected(modelData.origIndex)
                }
            }
        }

        Rectangle {
            Layout.fillWidth: true
            implicitHeight: 54
            radius: 8
            color: Qt.rgba(0, 0, 0, 0.28)
            border.width: 1
            border.color: StudioTheme.cardBorder

            ColumnLayout {
                anchors.fill: parent
                anchors.margins: 8
                spacing: 2

                Text {
                    text: "Folio 9480m • " + ((sidebarRoot.hwProfile.memory && sidebarRoot.hwProfile.memory.tier) || "8G") + " • " + ((sidebarRoot.hwProfile.power && sidebarRoot.hwProfile.power.source) || "AC")
                    color: StudioTheme.textPrimary
                    font.pixelSize: 11
                    font.weight: Font.DemiBold
                }
                Text {
                    text: "Blur: " + (sidebarRoot.effectiveConfig.effective_tier || "kawase_2pass") + " (" + (sidebarRoot.effectiveConfig.blur_passes !== undefined ? sidebarRoot.effectiveConfig.blur_passes : 2) + "p)"
                    color: StudioTheme.accentColor
                    font.pixelSize: 11
                }
            }
        }
    }
}
