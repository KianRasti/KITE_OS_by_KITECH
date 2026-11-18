pragma ComponentBehavior: Bound

import QtQuick
import Quickshell
import Quickshell.Io
import Quickshell.Hyprland

Item {
    id: state

    property string activeOverlay: ""
    property bool startMenuOpen: activeOverlay === "start"
    property bool quickSettingsOpen: activeOverlay === "quickSettings"
    property bool notificationsOpen: activeOverlay === "notifications"
    property bool snapLayoutsOpen: activeOverlay === "snapLayouts"

    // Persisted user settings (~/.config/kite-os/settings.json)
    property string themePreset: "Aero Blue"
    property string accentColor: "#38BDF8"
    property string taskbarAlignment: "center"
    property real transparency: 0.72
    property int blurRadius: 6
    property real specularEdgeBrightness: 0.35
    property int cornerRadius: 12
    property real animationSpeed: 1.0
    property string springCurve: "cubic-bezier(0.22, 1.0, 0.36, 1.0)"
    property string wallpaper: "aero-glass-wave"
    property bool batteryGlassAutosimplify: true
    property bool mitigationsOffRequested: false

    // Hardware profile (/run/kite-os/hw-profile.json)
    property int ramMb: 8192
    property string memoryTier: "8G"
    property string powerSource: "AC"

    // Surface tint map from canonical 5 presets
    readonly property var presetTintMap: ({
        "Aero Blue": "#0F172A",
        "Frosted Obsidian": "#090D16",
        "Emerald Glass": "#06201A",
        "Sunset Mica": "#1F1218",
        "Ultra-Light Flat": "#111827"
    })

    readonly property color surfaceTint: presetTintMap[themePreset] || "#0F172A"

    // Bounded Intel HD 4400 Clamping Precedence
    readonly property bool is4G: ramMb < 6144 || memoryTier === "4G"
    readonly property bool isFlat: themePreset === "Ultra-Light Flat" || blurRadius <= 0
    readonly property bool effectiveBlurEnabled: !is4G && !isFlat
    readonly property int effectiveBlurPasses: {
        if (!effectiveBlurEnabled) return 0
        if (powerSource === "Battery" && batteryGlassAutosimplify) return 1
        return 2
    }
    readonly property int effectiveBlurSize: {
        if (!effectiveBlurEnabled) return 0
        if (powerSource === "Battery" && batteryGlassAutosimplify) return Math.max(1, Math.min(blurRadius, 4))
        return Math.max(1, Math.min(blurRadius, 6))
    }
    readonly property string effectiveBlurTier: {
        if (is4G) return "static"
        if (isFlat) return "flat"
        if (powerSource === "Battery" && batteryGlassAutosimplify) return "kawase_1pass"
        if (powerSource === "Battery") return "kawase_2pass"
        return memoryTier === "16G" ? "kawase_full" : "kawase_2pass"
    }
    readonly property real effectiveOpacity: effectiveBlurEnabled ? transparency : Math.max(0.90, transparency)
    readonly property int animMs: animationSpeed <= 0 ? 0 : Math.max(40, Math.round(180 / animationSpeed))

    // Platform map for KiteBridge desktop entries: id -> "win"|"android"|"macos"|"linux"
    property var kiteBridgePlatforms: ({})

    function toggleOverlay(name) {
        activeOverlay = (activeOverlay === name) ? "" : name
    }

    function closeOverlays() {
        activeOverlay = ""
    }

    function resolvePlatform(entry) {
        if (!entry) return "linux"
        var id = String(entry.id || "")
        if (kiteBridgePlatforms[id]) return kiteBridgePlatforms[id]
        var idLower = id.toLowerCase()
        var title = String(entry.name || "")
        var titleLower = title.toLowerCase()
        if (
            title.indexOf("[Win]") !== -1 ||
            titleLower.indexOf("[win]") !== -1 ||
            idLower.indexOf("kitebridge-win") === 0 ||
            idLower.indexOf("wine") !== -1 ||
            idLower.indexOf(".exe") !== -1 ||
            titleLower.indexOf(".exe") !== -1
        ) return "win"
        if (
            title.indexOf("[Android]") !== -1 ||
            titleLower.indexOf("[android]") !== -1 ||
            idLower.indexOf("kitebridge-android") === 0 ||
            idLower.indexOf("waydroid") !== -1
        ) return "android"
        if (
            title.indexOf("[macOS]") !== -1 ||
            titleLower.indexOf("[macos]") !== -1 ||
            idLower.indexOf("kitebridge-macos") === 0 ||
            idLower.indexOf("darling") !== -1
        ) return "macos"
        return "linux"
    }

    function platformTagText(platform) {
        if (platform === "win") return "[Win]"
        if (platform === "android") return "[Android]"
        if (platform === "macos") return "[macOS]"
        return "Linux"
    }

    function toggleTaskbarAlignment() {
        var nextAlign = taskbarAlignment === "center" ? "left" : "center"
        taskbarAlignment = nextAlign
        cliAction.command = ["kite-settings", "--cli", "set", "--taskbar-alignment", nextAlign]
        cliAction.running = true
    }

    function openSettings() {
        closeOverlays()
        launchProcess.command = ["kite-settings"]
        launchProcess.running = true
    }

    function launchCommand(cmd) {
        closeOverlays()
        launchProcess.command = ["sh", "-c", cmd]
        launchProcess.running = true
    }

    function cycleActiveWindow() {
        Hyprland.dispatch("cyclenext")
    }

    function snapActiveWindow(zoneId, screenWidth, screenHeight) {
        var barHeight = 48
        var gap = 8
        var usableW = Math.max(640, screenWidth - gap * 2)
        var usableH = Math.max(400, screenHeight - barHeight - gap * 2)
        var x = gap
        var y = gap
        var w = usableW
        var h = usableH

        if (zoneId === "left-half") {
            w = Math.floor((usableW - gap) / 2)
        } else if (zoneId === "right-half") {
            w = Math.floor((usableW - gap) / 2)
            x = gap + w + gap
        } else if (zoneId === "split-60") {
            w = Math.floor((usableW - gap) * 0.60)
        } else if (zoneId === "split-40") {
            var left60 = Math.floor((usableW - gap) * 0.60)
            x = gap + left60 + gap
            w = usableW - left60 - gap
        } else if (zoneId === "top-left") {
            w = Math.floor((usableW - gap) / 2)
            h = Math.floor((usableH - gap) / 2)
        } else if (zoneId === "top-right") {
            w = Math.floor((usableW - gap) / 2)
            x = gap + w + gap
            h = Math.floor((usableH - gap) / 2)
        } else if (zoneId === "bottom-left") {
            w = Math.floor((usableW - gap) / 2)
            h = Math.floor((usableH - gap) / 2)
            y = gap + h + gap
        } else if (zoneId === "bottom-right") {
            w = Math.floor((usableW - gap) / 2)
            x = gap + w + gap
            h = Math.floor((usableH - gap) / 2)
            y = gap + h + gap
        }

        Hyprland.dispatch("setfloating active")
        Hyprland.dispatch("resizeactive exact " + w + " " + h)
        Hyprland.dispatch("moveactive exact " + x + " " + y)
        closeOverlays()
    }

    function parseSettings(raw) {
        try {
            var data = JSON.parse(raw)
            if (data.theme_preset) themePreset = data.theme_preset
            if (data.accent_color) accentColor = data.accent_color
            if (data.taskbar_alignment) taskbarAlignment = data.taskbar_alignment
            if (data.transparency !== undefined) transparency = data.transparency
            if (data.blur_radius !== undefined) blurRadius = data.blur_radius
            if (data.specular_edge_brightness !== undefined) specularEdgeBrightness = data.specular_edge_brightness
            if (data.corner_radius !== undefined) cornerRadius = data.corner_radius
            if (data.animation_speed !== undefined) animationSpeed = data.animation_speed
            if (data.spring_curve) springCurve = data.spring_curve
            if (data.wallpaper) wallpaper = data.wallpaper
            if (data.battery_glass_autosimplify !== undefined) batteryGlassAutosimplify = data.battery_glass_autosimplify
            if (data.mitigations_off_requested !== undefined) mitigationsOffRequested = data.mitigations_off_requested
        } catch (err) {
            console.warn("ShellState settings parse error:", err)
        }
    }

    function parseHwProfile(raw) {
        try {
            var data = JSON.parse(raw)
            if (data.ram_mb !== undefined) ramMb = data.ram_mb
            if (data.memory && data.memory.tier) memoryTier = data.memory.tier
            if (data.power && data.power.source) powerSource = data.power.source
        } catch (err) {
            console.warn("ShellState hw-profile parse error:", err)
        }
    }

    FileView {
        id: settingsFile
        path: Quickshell.env("HOME") + "/.config/kite-os/settings.json"
        watchChanges: true
        onLoaded: state.parseSettings(text())
        onFileChanged: {
            reload()
            state.parseSettings(text())
        }
    }

    FileView {
        id: hwProfileFile
        path: "/run/kite-os/hw-profile.json"
        watchChanges: true
        onLoaded: state.parseHwProfile(text())
        onFileChanged: {
            reload()
            state.parseHwProfile(text())
        }
    }

    Process {
        id: desktopPlatformScanner
        command: ["sh", "-c", "grep -H '^X-KiteBridge-Platform=' \"$HOME/.local/share/applications\"/kitebridge-*.desktop 2>/dev/null || true"]
        running: true
        stdout: StdioCollector {
            onStreamFinished: {
                var nextMap = {}
                var lines = (this.text || "").split("\n")
                for (var i = 0; i < lines.length; i++) {
                    var line = lines[i].trim()
                    if (!line) continue
                    var parts = line.split(":X-KiteBridge-Platform=")
                    if (parts.length === 2) {
                        var fileName = parts[0].split("/").pop().replace(".desktop", "")
                        nextMap[fileName] = parts[1].trim().toLowerCase()
                    }
                }
                state.kiteBridgePlatforms = nextMap
            }
        }
    }

    Process {
        id: launchProcess
    }

    Process {
        id: cliAction
    }
}
