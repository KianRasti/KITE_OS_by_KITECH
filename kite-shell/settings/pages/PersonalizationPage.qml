pragma ComponentBehavior: Bound

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
    property var presets: []

    signal presetRequested(string presetName)
    signal settingRequested(var args)

    clip: true

    readonly property var accentSwatches: [
        "#38BDF8", "#818CF8", "#10B981", "#FB923C", "#60A5FA", "#F43F5E"
    ]

    readonly property var springCurves: [
        { label: "Snappy (Default)", value: "cubic-bezier(0.22, 1.0, 0.36, 1.0)" },
        { label: "Smooth", value: "cubic-bezier(0.16, 1.0, 0.3, 1.0)" },
        { label: "Gentle Mica", value: "cubic-bezier(0.25, 1.0, 0.5, 1.0)" },
        { label: "Linear / Flat", value: "cubic-bezier(0.2, 0.0, 0.0, 1.0)" }
    ]

    readonly property var wallpaperOptions: [
        "aero-glass-wave",
        "obsidian-minimal-mesh",
        "emerald-aurora",
        "sunset-mica-horizon",
        "ultra-light-slate"
    ]

    function springCurveIndex(curveValue) {
        var target = String(curveValue || "cubic-bezier(0.22, 1.0, 0.36, 1.0)").trim()
        for (var i = 0; i < springCurves.length; i++) {
            if (springCurves[i].value === target) {
                return i
            }
        }
        return 0
    }

    ColumnLayout {
        width: page.availableWidth
        spacing: 10

        LivePreviewPane {
            settings: page.settings
            effective: page.effective
        }

        GlassCard {
            title: "Glass Preset Themes"
            subtitle: "Curated Intel HD 4400 visual profiles"

            Flow {
                Layout.fillWidth: true
                spacing: 8

                Repeater {
                    model: page.presets
                    delegate: PresetSwatchCard {
                        required property var modelData
                        presetName: modelData.name
                        accentColor: modelData.accent_color
                        surfaceTint: modelData.surface_tint
                        transparency: modelData.transparency
                        blurRadius: modelData.blur_radius
                        selected: (page.settings.theme_preset || "Aero Blue") === modelData.name
                        onClicked: page.presetRequested(modelData.name)
                    }
                }
            }
        }

        GlassCard {
            title: "Glass Material & Motion"
            subtitle: "Hardware bounds enforce <= 6px AC / <= 4px Battery / static 4G"

            GlassSlider {
                label: "Transparency"
                from: 0.20
                to: 1.00
                stepSize: 0.01
                value: page.settings.transparency !== undefined ? page.settings.transparency : 0.72
                valueText: Number(value).toFixed(2)
                onCommitted: function(val) {
                    page.settingRequested(["--transparency", Number(val).toFixed(2)])
                }
            }

            GlassSlider {
                label: "Blur Radius"
                from: 0
                to: 16
                stepSize: 1
                value: page.settings.blur_radius !== undefined ? page.settings.blur_radius : 6
                valueText: Math.round(value) + "px"
                clampHint: page.effective.clamped
                    ? ("Clamped to " + page.effective.blur_size + "px (" + page.effective.blur_passes + "p)")
                    : ""
                onCommitted: function(val) {
                    page.settingRequested(["--blur-radius", String(Math.round(val))])
                }
            }

            GlassSlider {
                label: "Specular Edge Brightness"
                from: 0.00
                to: 1.00
                stepSize: 0.01
                value: page.settings.specular_edge_brightness !== undefined ? page.settings.specular_edge_brightness : 0.35
                valueText: Number(value).toFixed(2)
                onCommitted: function(val) {
                    page.settingRequested(["--specular-edge-brightness", Number(val).toFixed(2)])
                }
            }

            GlassSlider {
                label: "Corner Radius"
                from: 0
                to: 24
                stepSize: 1
                value: page.settings.corner_radius !== undefined ? page.settings.corner_radius : 12
                valueText: Math.round(value) + "px"
                onCommitted: function(val) {
                    page.settingRequested(["--corner-radius", String(Math.round(val))])
                }
            }

            GlassSlider {
                label: "Animation Speed"
                from: 0.0
                to: 2.0
                stepSize: 0.05
                value: page.settings.animation_speed !== undefined ? page.settings.animation_speed : 1.0
                valueText: Number(value).toFixed(2) + "x"
                onCommitted: function(val) {
                    page.settingRequested(["--animation-speed", Number(val).toFixed(2)])
                }
            }

            RowLayout {
                Layout.fillWidth: true
                spacing: 8
                Text {
                    text: "Spring Curve"
                    color: StudioTheme.textPrimary
                    font.pixelSize: 13
                    Layout.fillWidth: true
                }
                ComboBox {
                    id: curveCombo
                    Layout.preferredWidth: 220
                    model: page.springCurves
                    textRole: "label"
                    currentIndex: page.springCurveIndex(page.settings.spring_curve)
                    onActivated: function(idx) {
                        page.settingRequested(["--spring-curve", page.springCurves[idx].value])
                    }
                }
            }
        }

        GlassCard {
            title: "Taskbar, Accent & Dynamic Wallpaper"

            RowLayout {
                Layout.fillWidth: true
                spacing: 8
                Text {
                    text: "Taskbar Alignment"
                    color: StudioTheme.textPrimary
                    font.pixelSize: 13
                    Layout.fillWidth: true
                }
                Button {
                    text: "Center"
                    highlighted: (page.settings.taskbar_alignment || "center") === "center"
                    onClicked: page.settingRequested(["--taskbar-alignment", "center"])
                }
                Button {
                    text: "Left"
                    highlighted: page.settings.taskbar_alignment === "left"
                    onClicked: page.settingRequested(["--taskbar-alignment", "left"])
                }
            }

            RowLayout {
                Layout.fillWidth: true
                spacing: 8
                Text {
                    text: "Accent Color"
                    color: StudioTheme.textPrimary
                    font.pixelSize: 13
                    Layout.fillWidth: true
                }
                Repeater {
                    model: page.accentSwatches
                    delegate: Rectangle {
                        required property string modelData
                        width: 24
                        height: 24
                        radius: 12
                        color: modelData
                        border.width: (page.settings.accent_color || "").toUpperCase() === modelData ? 2 : 1
                        border.color: "#FFFFFF"
                        MouseArea {
                            anchors.fill: parent
                            cursorShape: Qt.PointingHandCursor
                            onClicked: page.settingRequested(["--accent-color", modelData])
                        }
                    }
                }
            }

            RowLayout {
                Layout.fillWidth: true
                spacing: 8
                Text {
                    text: "Dynamic Wallpaper"
                    color: StudioTheme.textPrimary
                    font.pixelSize: 13
                    Layout.fillWidth: true
                }
                ComboBox {
                    Layout.preferredWidth: 220
                    model: page.wallpaperOptions
                    currentIndex: Math.max(0, page.wallpaperOptions.indexOf(page.settings.wallpaper || "aero-glass-wave"))
                    onActivated: function(idx) {
                        page.settingRequested(["--wallpaper", page.wallpaperOptions[idx]])
                    }
                }
            }
        }
    }
}
