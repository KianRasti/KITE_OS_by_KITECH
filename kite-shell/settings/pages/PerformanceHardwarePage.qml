import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../components"
import "../theme"

ScrollView {
    id: page
    property var settings: ({})
    property var effective: ({})
    property var hwProfile: ({})

    signal settingRequested(var args)
    clip: true

    Dialog {
        id: mitigationsDialog
        title: "Disable CPU Security Mitigations?"
        modal: true
        anchors.centerIn: Overlay.overlay
        standardButtons: Dialog.Ok | Dialog.Cancel

        onAccepted: {
            page.settingRequested(["--mitigations-off", "true", "--confirm-security-risk"])
        }

        ColumnLayout {
            spacing: 8
            width: 400
            Text {
                text: "Setting mitigations=off exposes this Haswell CPU to Spectre, Meltdown, MDS, and L1TF vulnerabilities. Requires a system reboot and is recommended only for trusted single-user workloads."
                wrapMode: Text.WordWrap
                color: StudioTheme.textPrimary
                Layout.fillWidth: true
            }
        }
    }

    ColumnLayout {
        width: page.availableWidth
        spacing: 10

        GlassCard {
            title: "Live Hardware Bento Telemetry (Folio 9480m)"
            subtitle: "Auto-scaled via kite-hw-tune & kite-aid.socket"

            GridLayout {
                Layout.fillWidth: true
                columns: 2
                columnSpacing: 10
                rowSpacing: 10

                GlassCard {
                    Layout.fillWidth: true
                    title: "Intel HD 4400 GPU Pins"
                    Text {
                        text: "OpenGL: crocus | VA-API: i965 | Vulkan: 1.2 (anv)"
                        color: StudioTheme.accentColor
                        font.pixelSize: 11
                        wrapMode: Text.WordWrap
                        Layout.fillWidth: true
                    }
                }

                GlassCard {
                    Layout.fillWidth: true
                    title: "ZRAM & Memory Tier"
                    Text {
                        text: "Tier: " + ((page.hwProfile.memory && page.hwProfile.memory.tier) || "8G") + " | " +
                              ((page.hwProfile.memory && page.hwProfile.memory.zram_percent) || 100) + "% " +
                              ((page.hwProfile.memory && page.hwProfile.memory.zram_algo) || "zstd")
                        color: StudioTheme.textPrimary
                        font.pixelSize: 11
                        wrapMode: Text.WordWrap
                        Layout.fillWidth: true
                    }
                }

                GlassCard {
                    Layout.fillWidth: true
                    title: "KiteBridge Runtimes"
                    Text {
                        text: "Wine: DXVK 1.10.3 + ntsync | Waydroid | OSX-KVM"
                        color: StudioTheme.textPrimary
                        font.pixelSize: 11
                        wrapMode: Text.WordWrap
                        Layout.fillWidth: true
                    }
                }

                GlassCard {
                    Layout.fillWidth: true
                    title: "Kite AI Index & Socket"
                    Text {
                        text: "0 MB idle (kite-aid.socket) | SQLite FTS5 + SimHash"
                        color: StudioTheme.accentColor
                        font.pixelSize: 11
                        wrapMode: Text.WordWrap
                        Layout.fillWidth: true
                    }
                }
            }
        }

        GlassCard {
            title: "Live Hardware Profile (/run/kite-os/hw-profile.json)"
            subtitle: "Dynamic auto-tuning from kite-hw-tune"

            Text {
                text: "RAM Tier: " + ((page.hwProfile.memory && page.hwProfile.memory.tier) || "8G") +
                      " | Power: " + ((page.hwProfile.power && page.hwProfile.power.source) || "AC") +
                      " | Effective Blur: " + (page.effective.effective_tier || "kawase_2pass") +
                      " (size=" + (page.effective.blur_size !== undefined ? page.effective.blur_size : 6) +
                      ", passes=" + (page.effective.blur_passes !== undefined ? page.effective.blur_passes : 2) + ")"
                color: StudioTheme.accentColor
                font.pixelSize: 12
                wrapMode: Text.WordWrap
                Layout.fillWidth: true
            }
        }

        GlassCard {
            title: "Power & Glass Optimization"

            GlassToggle {
                label: "Auto-simplify Glass on Battery"
                subtitle: "Automatically steps down Dual-Kawase blur to 1-pass (size <= 4) on battery power"
                checked: page.settings.battery_glass_autosimplify !== undefined ? page.settings.battery_glass_autosimplify : true
                onToggledRequested: function(nextVal) {
                    page.settingRequested(["--battery-autosimplify", nextVal ? "true" : "false"])
                }
            }
        }

        GlassCard {
            title: "Kernel CPU Speculative Execution Mitigations"

            WarningBanner {
                visible: page.settings.mitigations_off_requested === true
                severe: true
                message: "SECURITY WARNING: mitigations=off requested (requires reboot). System is exposed to Spectre/Meltdown/MDS/L1TF side-channel risks."
            }

            GlassToggle {
                label: "Request mitigations=off kernel flag (Optional)"
                subtitle: "Trades speculative execution security mitigations for extra Haswell syscall throughput (reboot required)"
                checked: page.settings.mitigations_off_requested === true
                onToggledRequested: function(nextVal) {
                    if (nextVal) {
                        mitigationsDialog.open()
                    } else {
                        page.settingRequested(["--mitigations-off", "false"])
                    }
                }
            }
        }
    }
}
