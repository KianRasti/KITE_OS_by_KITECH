import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import Quickshell
import "../components"
import "../theme"

ScrollView {
    id: page
    clip: true

    ColumnLayout {
        width: page.availableWidth
        spacing: 10

        GlassCard {
            title: "Local Session Account"
            subtitle: "Active Wayland desktop user"

            Text {
                text: "User: " + (Quickshell.env("USER") || "kite") + " • Home: " + (Quickshell.env("HOME") || "/home/kite")
                color: StudioTheme.accentColor
                font.pixelSize: 12
            }
        }

        GlassCard {
            title: "Unified User Directories Across Subsystems"
            subtitle: "Shared across Linux, Wine [Win], Waydroid [Android], and OSX-KVM [macOS]"

            Text {
                text: "~/Desktop, ~/Documents, and ~/Downloads map seamlessly into Wine prefixes and VirtIO-FS shares."
                color: StudioTheme.textSecondary
                font.pixelSize: 12
                wrapMode: Text.WordWrap
                Layout.fillWidth: true
            }
        }
    }
}
