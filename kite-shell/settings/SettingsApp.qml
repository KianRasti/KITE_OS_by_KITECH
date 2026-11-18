pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import Quickshell
import Quickshell.Io
import "theme"
import "components"
import "pages"

ShellRoot {
    id: root

    property int activePageIndex: 3
    property string searchFilter: ""

    property var settingsState: ({
        schema_version: 1,
        theme_preset: "Aero Blue",
        accent_color: "#38BDF8",
        taskbar_alignment: "center",
        transparency: 0.72,
        blur_radius: 6,
        specular_edge_brightness: 0.35,
        corner_radius: 12,
        animation_speed: 1.0,
        spring_curve: "cubic-bezier(0.22, 1.0, 0.36, 1.0)",
        wallpaper: "aero-glass-wave",
        battery_glass_autosimplify: true,
        mitigations_off_requested: false
    })

    property var hwProfileState: ({
        schema_version: 1,
        ram_mb: 8192,
        memory: { tier: "8G" },
        power: { source: "AC", epp: "balance_performance" },
        blur: { tier: "kawase_2pass", enabled: true, size: 6, passes: 2, xray: true },
        storage: [ { device: "sda", rotational: 0, scheduler: "kyber" } ]
    })

    property var effectiveState: ({
        blur_enabled: true,
        blur_size: 6,
        blur_passes: 2,
        blur_xray: true,
        effective_tier: "kawase_2pass",
        clamp_reason: "NONE",
        clamped: false,
        active_opacity: 0.92,
        inactive_opacity: 0.85,
        rounding: 12,
        requires_reboot: false
    })

    readonly property var canonicalPresets: [
        {
            name: "Aero Blue",
            accent_color: "#38BDF8",
            transparency: 0.72,
            blur_radius: 6,
            specular_edge_brightness: 0.35,
            corner_radius: 12,
            animation_speed: 1.0,
            spring_curve: "cubic-bezier(0.22, 1.0, 0.36, 1.0)",
            wallpaper: "aero-glass-wave",
            surface_tint: "#0F172A"
        },
        {
            name: "Frosted Obsidian",
            accent_color: "#818CF8",
            transparency: 0.78,
            blur_radius: 6,
            specular_edge_brightness: 0.28,
            corner_radius: 10,
            animation_speed: 1.0,
            spring_curve: "cubic-bezier(0.22, 1.0, 0.36, 1.0)",
            wallpaper: "obsidian-minimal-mesh",
            surface_tint: "#090D16"
        },
        {
            name: "Emerald Glass",
            accent_color: "#10B981",
            transparency: 0.70,
            blur_radius: 6,
            specular_edge_brightness: 0.40,
            corner_radius: 14,
            animation_speed: 1.0,
            spring_curve: "cubic-bezier(0.16, 1.0, 0.3, 1.0)",
            wallpaper: "emerald-aurora",
            surface_tint: "#06201A"
        },
        {
            name: "Sunset Mica",
            accent_color: "#FB923C",
            transparency: 0.76,
            blur_radius: 5,
            specular_edge_brightness: 0.32,
            corner_radius: 12,
            animation_speed: 0.95,
            spring_curve: "cubic-bezier(0.25, 1.0, 0.5, 1.0)",
            wallpaper: "sunset-mica-horizon",
            surface_tint: "#1F1218"
        },
        {
            name: "Ultra-Light Flat",
            accent_color: "#60A5FA",
            transparency: 0.96,
            blur_radius: 0,
            specular_edge_brightness: 0.15,
            corner_radius: 8,
            animation_speed: 1.35,
            spring_curve: "cubic-bezier(0.2, 0.0, 0.0, 1.0)",
            wallpaper: "ultra-light-slate",
            surface_tint: "#111827"
        }
    ]

    function syncStudioTheme() {
        StudioTheme.accentColor = settingsState.accent_color || "#38BDF8"
        StudioTheme.transparency = settingsState.transparency !== undefined ? settingsState.transparency : 0.72
        StudioTheme.cornerRadius = settingsState.corner_radius !== undefined ? settingsState.corner_radius : 12
        StudioTheme.specularBrightness = settingsState.specular_edge_brightness !== undefined ? settingsState.specular_edge_brightness : 0.35
        StudioTheme.animationSpeed = settingsState.animation_speed !== undefined ? settingsState.animation_speed : 1.0
        var presetName = settingsState.theme_preset || "Aero Blue"
        for (var i = 0; i < canonicalPresets.length; i++) {
            if (canonicalPresets[i].name === presetName) {
                StudioTheme.surfaceTint = canonicalPresets[i].surface_tint
                break
            }
        }
    }

    function applyCliPayload(rawText) {
        try {
            var payload = JSON.parse(rawText)
            if (payload.settings) settingsState = payload.settings
            if (payload.hw_profile) hwProfileState = payload.hw_profile
            if (payload.effective) effectiveState = payload.effective
            syncStudioTheme()
        } catch (err) {
            console.warn("kite-settings JSON parse error:", err)
        }
    }

    function runCli(args) {
        cliRunner.command = ["kite-settings", "--cli"].concat(args).concat(["--json"])
        cliRunner.running = true
    }

    function applyPreset(name) {
        runCli(["preset", name])
    }

    function setSettingArgs(args) {
        runCli(["set"].concat(args))
    }

    function resetDefaults() {
        runCli(["reset"])
    }

    Process {
        id: cliRunner
        command: ["kite-settings", "--cli", "show", "--json"]
        running: true
        stdout: StdioCollector {
            onStreamFinished: {
                if (this.text && this.text.trim().length > 0) {
                    root.applyCliPayload(this.text)
                }
            }
        }
    }

    FileView {
        id: settingsWatcher
        path: Quickshell.env("HOME") + "/.config/kite-os/settings.json"
        watchChanges: true
        onFileChanged: {
            reload()
            root.runCli(["show"])
        }
    }

    FileView {
        id: hwProfileWatcher
        path: "/run/kite-os/hw-profile.json"
        watchChanges: true
        onFileChanged: {
            reload()
            root.runCli(["sync"])
        }
    }

    FloatingWindow {
        id: studioWindow
        title: "KITE_OS Settings Studio"
        implicitWidth: 1020
        implicitHeight: 680
        color: "transparent"
        visible: true

        Rectangle {
            anchors.fill: parent
            radius: StudioTheme.cornerRadius
            color: StudioTheme.panelBackground
            border.width: 1
            border.color: StudioTheme.specularBorder

            RowLayout {
                anchors.fill: parent
                anchors.margins: 12
                spacing: 12

                SidebarNav {
                    id: sidebar
                    Layout.preferredWidth: 230
                    Layout.fillHeight: true
                    currentIndex: root.activePageIndex
                    searchFilter: root.searchFilter
                    hwProfile: root.hwProfileState
                    effectiveConfig: root.effectiveState
                    onCategorySelected: function(idx) {
                        root.activePageIndex = idx
                    }
                    onSearchChanged: function(query) {
                        root.searchFilter = query
                    }
                }

                ColumnLayout {
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    spacing: 10

                    RowLayout {
                        Layout.fillWidth: true
                        spacing: 10

                        Text {
                            text: sidebar.categories[root.activePageIndex].title
                            color: StudioTheme.textPrimary
                            font.pixelSize: 20
                            font.weight: Font.DemiBold
                            Layout.fillWidth: true
                        }

                        Button {
                            text: "Reset Aero Blue"
                            onClicked: root.resetDefaults()
                        }
                    }

                    StackLayout {
                        Layout.fillWidth: true
                        Layout.fillHeight: true
                        currentIndex: root.activePageIndex

                        SystemPage {
                            hwProfile: root.hwProfileState
                        }
                        BluetoothDevicesPage {
                            hwProfile: root.hwProfileState
                        }
                        NetworkInternetPage {
                            hwProfile: root.hwProfileState
                        }
                        PersonalizationPage {
                            settings: root.settingsState
                            effective: root.effectiveState
                            hwProfile: root.hwProfileState
                            presets: root.canonicalPresets
                            onPresetRequested: function(name) { root.applyPreset(name) }
                            onSettingRequested: function(args) { root.setSettingArgs(args) }
                        }
                        AppsKiteBridgePage {
                            hwProfile: root.hwProfileState
                        }
                        PerformanceHardwarePage {
                            settings: root.settingsState
                            effective: root.effectiveState
                            hwProfile: root.hwProfileState
                            onSettingRequested: function(args) { root.setSettingArgs(args) }
                        }
                        AccountsPage {
                        }
                        SystemUpdatePage {
                        }
                        AiIndexingPage {
                            hwProfile: root.hwProfileState
                        }
                    }
                }
            }
        }
    }
}
