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
            title: "Bluetooth"
            subtitle: "Intel Wireless 7260 Bluetooth Adapter (btusb)"

            GlassToggle {
                label: "Bluetooth radio"
                subtitle: "Pair headsets, mice, and Folio accessories"
                checked: true
            }
        }

        GlassCard {
            title: "Synaptics LuxPad & Pointing Stick"
            subtitle: "Haswell Folio trackpad, tap-to-click, and TrackPoint"

            GlassToggle {
                label: "Tap to click"
                subtitle: "Enabled in Hyprland input configuration"
                checked: true
            }
            GlassToggle {
                label: "Disable touchpad while typing"
                subtitle: "Prevents accidental palm movement"
                checked: true
            }
        }

        GlassCard {
            title: "Biometrics"
            subtitle: "Validity VFS495 Fingerprint Sensor"

            Text {
                text: "Managed via fprintd / polkit authentication agent."
                color: StudioTheme.textSecondary
                font.pixelSize: 12
            }
        }
    }
}
