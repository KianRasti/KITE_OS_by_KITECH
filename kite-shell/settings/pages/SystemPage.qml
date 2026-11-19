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
            title: "KITE_OS™ — Built by KITech"
            subtitle: "Created by Kian Rasti • portfolio.kitech.info • kian.kitech.info"

            Text {
                text: "Edition: KITE_OS™ 1.0 (Arch / CachyOS x86-64-v3) • Source: github.com/KianRasti/KITE_OS_by_KITECH"
                color: StudioTheme.textSecondary
                font.pixelSize: 12
                wrapMode: Text.WordWrap
                Layout.fillWidth: true
            }
        }

        GlassCard {
            title: "HP EliteBook Folio 9480m Hardware"
            subtitle: "4th Gen Haswell ULT • Intel HD Graphics 4400 GT2"

            Text {
                text: "Graphics Stack: Mesa crocus (OpenGL 4.6) • ANV Vulkan 1.2 • libva-intel-driver (i965)"
                color: StudioTheme.textSecondary
                font.pixelSize: 12
                wrapMode: Text.WordWrap
                Layout.fillWidth: true
            }
            Text {
                text: "Memory Tier: " + ((page.hwProfile.memory && page.hwProfile.memory.tier) || "8G") + " (" + (page.hwProfile.ram_mb || 8192) + " MB)"
                color: StudioTheme.accentColor
                font.pixelSize: 12
                font.weight: Font.DemiBold
            }
        }

        GlassCard {
            title: "Display & Sound"
            subtitle: "eDP-1 Panel (1366x768 / 1600x900 @ 60Hz) • PipeWire IDT 92HD91BXX"

            Text {
                text: "Hyprland VFR damage tracking enabled for zero idle GPU wakeups."
                color: StudioTheme.textSecondary
                font.pixelSize: 12
            }
        }

        GlassCard {
            title: "Storage & Btrfs Layout"
            subtitle: "Mount options: compress=zstd:1,noatime"

            Text {
                text: "Subvolumes: @ (/), @home (/home), @kitebridge (/var/lib/kitebridge), @snapshots (/.snapshots)"
                color: StudioTheme.textSecondary
                font.pixelSize: 12
                wrapMode: Text.WordWrap
                Layout.fillWidth: true
            }
        }
    }
}
