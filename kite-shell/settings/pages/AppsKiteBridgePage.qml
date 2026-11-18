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
            title: "[Win] Windows Subsystem (Wine-CachyOS + ntsync)"
            subtitle: "DXVK pinned strictly to 1.10.3 • DX12 routed to WineD3D OpenGL 4.6 (crocus)"

            Text {
                text: "Overrides: d3d9, d3d10core, d3d11, dxgi -> DXVK 1.10.3"
                color: StudioTheme.accentColor
                font.pixelSize: 12
            }
        }

        GlassCard {
            title: "[Android] Waydroid Multi-Window Runtime"
            subtitle: "persist.waydroid.multi_windows=true • binder_linux • libndk/libhoudini"

            Text {
                text: "Idle Policy: " + ((page.hwProfile.subsystems && page.hwProfile.subsystems.waydroid && page.hwProfile.subsystems.waydroid.idle_policy) || "cgroup_freeze")
                color: StudioTheme.textSecondary
                font.pixelSize: 12
            }
        }

        GlassCard {
            title: "[macOS] Darling & OSX-KVM Haswell Bridge"
            subtitle: "Native DMG/APFS/HFS+ mount (darling-dmg, hfsprogs, apfs-fuse) + -cpu Haswell-noTSX,+invtsc"

            Text {
                text: "VirtIO-FS shares ~/Desktop, ~/Documents, and ~/Downloads seamlessly."
                color: StudioTheme.textSecondary
                font.pixelSize: 12
                wrapMode: Text.WordWrap
                Layout.fillWidth: true
            }
        }
    }
}
