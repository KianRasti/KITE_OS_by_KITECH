import QtQuick
import QtQuick.Layouts
import calamares.slideshow 1.0

Presentation {
    id: presentation
    width: parent ? parent.width : 720
    height: parent ? parent.height : 500

    property int currentSlide: 0

    readonly property var slides: [
        {
            "title": "Haswell x86-64-v3 Performance",
            "subtitle": "CachyOS Kernel + Mesa Crocus & Intel i965",
            "body": "Built for HP EliteBook Folio 9480m with x86-64-v3 AVX2/FMA3 packages, linux-cachyos, Mesa crocus OpenGL 4.6, Vulkan 1.2 anv, and i965 VA-API.",
            "image": "assets/slide-haswell.svg"
        },
        {
            "title": "Dynamic Hardware Auto-Tuner",
            "subtitle": "4 GB / 8 GB / 16 GB RAM & Storage Scaling",
            "body": "kite-hw-tune detects DDR3L capacity, configures tiered zram compression, sets SSD kyber or HDD bfq I/O schedulers, and manages AC vs battery EPP.",
            "image": "assets/slide-hwtune.svg"
        },
        {
            "title": "Windows 11 Glass UI Shell",
            "subtitle": "60 FPS Hyprland + Quickshell Aero Blue",
            "body": "Bounded 2-pass Dual-Kawase Glass blur on AC, Win+A Quick Settings, Win+N Notification Center, Win+Z Snap Layouts, and live kite-settings customization.",
            "image": "assets/slide-glass.svg"
        },
        {
            "title": "KiteBridge & Btrfs Snapshots",
            "subtitle": "Windows, Android & macOS Apps on zstd:1 Btrfs",
            "body": "Run .exe/.msi via ntsync + DXVK 1.10.3, .apk via Waydroid multi-window, and .dmg/.app via Darling/OSX-KVM inside compressed @kitebridge subvolumes.",
            "image": "assets/slide-bridge.svg"
        }
    ]

    function onActivate() {
        currentSlide = 0
        slideTimer.start()
    }

    function onLeave() {
        slideTimer.stop()
    }

    Timer {
        id: slideTimer
        interval: 6500
        running: presentation.activatedInCalamares
        repeat: true
        onTriggered: {
            presentation.currentSlide = (presentation.currentSlide + 1) % presentation.slides.length
        }
    }

    Rectangle {
        anchors.fill: parent
        color: "#0B1120"

        Rectangle {
            anchors.centerIn: parent
            width: Math.min(parent.width - 48, 660)
            height: Math.min(parent.height - 48, 420)
            radius: 12
            color: Qt.rgba(30 / 255, 41 / 255, 59 / 255, 0.72)
            border.width: 1
            border.color: Qt.rgba(1, 1, 1, 0.18)

            Rectangle {
                anchors.fill: parent
                anchors.margins: 1
                radius: 11
                color: "transparent"
                border.width: 1
                border.color: Qt.rgba(56 / 255, 189 / 255, 248 / 255, 0.28)
            }

            ColumnLayout {
                anchors.fill: parent
                anchors.margins: 28
                spacing: 16

                Image {
                    id: slideImage
                    Layout.alignment: Qt.AlignHCenter
                    Layout.preferredWidth: 240
                    Layout.preferredHeight: 160
                    fillMode: Image.PreserveAspectFit
                    source: presentation.slides[presentation.currentSlide].image
                    smooth: true

                    Behavior on opacity {
                        NumberAnimation {
                            duration: 300
                            easing.type: Easing.OutCubic
                        }
                    }
                }

                Text {
                    Layout.fillWidth: true
                    horizontalAlignment: Text.AlignHCenter
                    text: presentation.slides[presentation.currentSlide].title
                    color: "#F8FAFC"
                    font.pixelSize: 22
                    font.bold: true
                }

                Text {
                    Layout.fillWidth: true
                    horizontalAlignment: Text.AlignHCenter
                    text: presentation.slides[presentation.currentSlide].subtitle
                    color: "#38BDF8"
                    font.pixelSize: 14
                    font.weight: Font.DemiBold
                }

                Text {
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    horizontalAlignment: Text.AlignHCenter
                    verticalAlignment: Text.AlignTop
                    wrapMode: Text.WordWrap
                    text: presentation.slides[presentation.currentSlide].body
                    color: "#CBD5E1"
                    font.pixelSize: 13
                    lineHeight: 1.35
                }

                RowLayout {
                    Layout.alignment: Qt.AlignHCenter
                    spacing: 10

                    Repeater {
                        model: presentation.slides.length

                        Rectangle {
                            required property int index
                            width: index === presentation.currentSlide ? 28 : 10
                            height: 8
                            radius: 4
                            color: index === presentation.currentSlide
                                ? "#38BDF8"
                                : Qt.rgba(148 / 255, 163 / 255, 184 / 255, 0.45)

                            Behavior on width {
                                NumberAnimation {
                                    duration: 240
                                    easing.type: Easing.OutCubic
                                }
                            }

                            MouseArea {
                                anchors.fill: parent
                                cursorShape: Qt.PointingHandCursor
                                onClicked: {
                                    presentation.currentSlide = index
                                    slideTimer.restart()
                                }
                            }
                        }
                    }
                }
            }
        }
    }
}
