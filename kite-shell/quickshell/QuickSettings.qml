pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import Quickshell
import Quickshell.Wayland
import Quickshell.Services.Pipewire
import "components"

PanelWindow {
    id: qsWindow
    required property ShellState shellState

    visible: shellState.quickSettingsOpen
    anchors {
        bottom: true
        right: true
    }
    margins {
        bottom: 58
        right: 12
    }

    implicitWidth: 380
    implicitHeight: 460
    color: "transparent"
    WlrLayershell.namespace: "quickshell"
    WlrLayershell.keyboardFocus: WlrKeyboardFocus.OnDemand

    property bool wifiEnabled: true
    property bool bluetoothEnabled: true
    property string powerMode: "Balanced"
    property real brightnessValue: 75

    readonly property var streamNodes: {
        var nodes = Pipewire.nodes && Pipewire.nodes.values ? Pipewire.nodes.values : []
        var result = []
        for (var i = 0; i < nodes.length; i++) {
            var n = nodes[i]
            if (n && n.isStream && !n.isSink) {
                result.push(n)
            }
        }
        return result
    }

    readonly property var playbackStreams: {
        var result = []
        for (var i = 0; i < streamNodes.length; i++) {
            var n = streamNodes[i]
            if (n && n.audio) {
                result.push(n)
            }
        }
        return result
    }

    PwObjectTracker {
        objects: {
            var list = []
            if (Pipewire.defaultAudioSink) {
                list.push(Pipewire.defaultAudioSink)
            }
            for (var i = 0; i < qsWindow.streamNodes.length; i++) {
                list.push(qsWindow.streamNodes[i])
            }
            return list
        }
    }

    GlassPanel {
        anchors.fill: parent
        shellState: qsWindow.shellState

        ColumnLayout {
            anchors.fill: parent
            anchors.margins: 14
            spacing: 10

            RowLayout {
                Layout.fillWidth: true
                Text {
                    text: "Quick Settings"
                    color: "#F8FAFC"
                    font.pixelSize: 15
                    font.weight: Font.Bold
                    Layout.fillWidth: true
                }
                Text {
                    text: qsWindow.shellState.memoryTier + " • " + qsWindow.shellState.powerSource + " • " + qsWindow.shellState.effectiveBlurTier
                    color: qsWindow.shellState.accentColor
                    font.pixelSize: 11
                    font.weight: Font.DemiBold
                }
            }

            // Quick Toggles Grid
            GridLayout {
                Layout.fillWidth: true
                columns: 2
                columnSpacing: 8
                rowSpacing: 8

                Button {
                    Layout.fillWidth: true
                    text: qsWindow.wifiEnabled ? "Wi-Fi: On (7260)" : "Wi-Fi: Off"
                    highlighted: qsWindow.wifiEnabled
                    onClicked: {
                        qsWindow.wifiEnabled = !qsWindow.wifiEnabled
                        qsWindow.shellState.launchCommand("nmcli radio wifi " + (qsWindow.wifiEnabled ? "on" : "off"))
                    }
                }

                Button {
                    Layout.fillWidth: true
                    text: qsWindow.bluetoothEnabled ? "Bluetooth: On" : "Bluetooth: Off"
                    highlighted: qsWindow.bluetoothEnabled
                    onClicked: {
                        qsWindow.bluetoothEnabled = !qsWindow.bluetoothEnabled
                        qsWindow.shellState.launchCommand("bluetoothctl power " + (qsWindow.bluetoothEnabled ? "on" : "off"))
                    }
                }

                Button {
                    Layout.fillWidth: true
                    text: "Power: " + qsWindow.powerMode
                    onClicked: {
                        if (qsWindow.powerMode === "Efficiency") qsWindow.powerMode = "Balanced"
                        else if (qsWindow.powerMode === "Balanced") qsWindow.powerMode = "Turbo"
                        else qsWindow.powerMode = "Efficiency"
                    }
                }

                Button {
                    Layout.fillWidth: true
                    text: qsWindow.shellState.effectiveBlurEnabled ? "Glass FX: Active" : "Glass FX: Static"
                    highlighted: qsWindow.shellState.effectiveBlurEnabled
                    onClicked: qsWindow.shellState.openSettings()
                }
            }

            // Brightness Slider
            ColumnLayout {
                Layout.fillWidth: true
                spacing: 2
                Text {
                    text: "Display Brightness: " + Math.round(qsWindow.brightnessValue) + "%"
                    color: "#CBD5E1"
                    font.pixelSize: 12
                }
                Slider {
                    Layout.fillWidth: true
                    from: 5
                    to: 100
                    stepSize: 5
                    value: qsWindow.brightnessValue
                    onMoved: {
                        qsWindow.brightnessValue = value
                        qsWindow.shellState.launchCommand("brightnessctl set " + Math.round(value) + "%")
                    }
                }
            }

            // Master Volume (PipeWire)
            ColumnLayout {
                Layout.fillWidth: true
                spacing: 2
                Text {
                    text: "Master Volume (PipeWire)"
                    color: "#CBD5E1"
                    font.pixelSize: 12
                }
                Slider {
                    Layout.fillWidth: true
                    from: 0.0
                    to: 1.0
                    value: Pipewire.defaultAudioSink && Pipewire.defaultAudioSink.audio ? Pipewire.defaultAudioSink.audio.volume : 0.7
                    onMoved: {
                        if (Pipewire.defaultAudioSink && Pipewire.defaultAudioSink.audio) {
                            Pipewire.defaultAudioSink.audio.volume = value
                        }
                    }
                }
            }

            // Per-App PipeWire Mixer
            Text {
                text: "Per-App Audio Mixer"
                color: "#94A3B8"
                font.pixelSize: 11
                font.weight: Font.DemiBold
            }

            ListView {
                Layout.fillWidth: true
                Layout.fillHeight: true
                clip: true
                spacing: 6
                model: qsWindow.playbackStreams
                delegate: RowLayout {
                    required property var modelData
                    width: ListView.view.width
                    spacing: 8

                    Text {
                        text: modelData.description || modelData.name || "Stream"
                        color: "#E2E8F0"
                        font.pixelSize: 11
                        elide: Text.ElideRight
                        Layout.preferredWidth: 130
                    }

                    Slider {
                        Layout.fillWidth: true
                        from: 0.0
                        to: 1.0
                        value: modelData.audio ? modelData.audio.volume : 1.0
                        onMoved: {
                            if (modelData.audio) modelData.audio.volume = value
                        }
                    }
                }
            }
        }
    }
}
