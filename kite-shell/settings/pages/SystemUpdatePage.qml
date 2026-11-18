import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../components"
import "../theme"

ScrollView {
    id: page
    clip: true

    ColumnLayout {
        width: page.availableWidth
        spacing: 10

        GlassCard {
            title: "KITE_OS System Updates"
            subtitle: "Arch Linux / CachyOS x86-64-v3 Haswell Profile"

            Text {
                text: "Kernel: linux-cachyos (ntsync, binder_linux, zram) • Snapshot hook: Btrfs @snapshots"
                color: StudioTheme.textSecondary
                font.pixelSize: 12
                wrapMode: Text.WordWrap
                Layout.fillWidth: true
            }

            Button {
                text: "Verify Hardware Invariants"
                enabled: false
            }
        }
    }
}
