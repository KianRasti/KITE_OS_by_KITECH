import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../components"
import "../theme"

ScrollView {
    id: page
    property var hwProfile: ({})
    clip: true

    ColumnLayout {
        width: page.availableWidth
        spacing: 10

        GlassCard {
            title: "Wi-Fi (Intel Wireless 7260)"
            subtitle: "iwlwifi kernel driver with AC/Battery power-save scaling"

            GlassToggle {
                label: "Wi-Fi Radio"
                subtitle: "NetworkManager iwlwifi interface"
                checked: true
            }
            Text {
                text: "Power Source: " + ((page.hwProfile.power && page.hwProfile.power.source) || "AC")
                color: StudioTheme.accentColor
                font.pixelSize: 12
            }
        }

        GlassCard {
            title: "Ethernet (Intel I218-LM)"
            subtitle: "e1000e Gigabit Ethernet controller"

            Text {
                text: "Hardware link managed by systemd-networkd / NetworkManager."
                color: StudioTheme.textSecondary
                font.pixelSize: 12
            }
        }
    }
}
