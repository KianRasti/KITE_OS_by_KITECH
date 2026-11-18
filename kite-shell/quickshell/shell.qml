pragma ComponentBehavior: Bound

import QtQuick
import Quickshell
import Quickshell.Hyprland

ShellRoot {
    id: root

    ShellState {
        id: shellState
    }

    GlobalShortcut {
        appid: "kite"
        name: "toggleStartMenu"
        description: "Toggle Windows 11-style Start Menu"
        onPressed: shellState.toggleOverlay("start")
    }

    GlobalShortcut {
        appid: "kite"
        name: "toggleQuickSettings"
        description: "Toggle Quick Settings (Win+A)"
        onPressed: shellState.toggleOverlay("quickSettings")
    }

    GlobalShortcut {
        appid: "kite"
        name: "toggleNotifications"
        description: "Toggle Notifications & Calendar (Win+N)"
        onPressed: shellState.toggleOverlay("notifications")
    }

    GlobalShortcut {
        appid: "kite"
        name: "toggleSnapLayouts"
        description: "Toggle Snap Layouts (Win+Z)"
        onPressed: shellState.toggleOverlay("snapLayouts")
    }

    GlobalShortcut {
        appid: "kite"
        name: "toggleTaskView"
        description: "Cycle active windows (Win+Tab)"
        onPressed: shellState.cycleActiveWindow()
    }

    Variants {
        model: Quickshell.screens
        delegate: Taskbar {
            required property ShellScreen modelData
            screen: modelData
            shellState: shellState
        }
    }

    StartMenu {
        shellState: shellState
    }

    QuickSettings {
        shellState: shellState
    }

    NotificationCenter {
        shellState: shellState
    }

    SnapLayouts {
        shellState: shellState
    }
}
