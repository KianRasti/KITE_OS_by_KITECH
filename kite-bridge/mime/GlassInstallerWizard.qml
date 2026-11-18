import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

ApplicationWindow {
    id: root
    visible: true
    width: 560
    height: 420
    title: "KiteBridge Glass Installer Wizard"
    color: "transparent"

    property string planJson: ""
    Component.onCompleted: {
        if ((!planJson || planJson.length === 0) && typeof Qt !== "undefined" && Qt.application && Qt.application.arguments) {
            var args = Qt.application.arguments;
            for (var i = 0; i < args.length; i++) {
                if (args[i].indexOf("--plan=") === 0) {
                    planJson = args[i].slice(7);
                    break;
                }
            }
        }
    }
    property var planData: {
        if (planJson && planJson.length > 0) {
            try { return JSON.parse(planJson); } catch (e) { return {}; }
        }
        return {
            app_name: "KiteBridge Application",
            platform_tag: "[Win]",
            handler: "wine-ntsync",
            dxvk_version: "1.10.3",
            target_prefix: "/var/lib/kitebridge",
            steps: [
                "Inspect container & verify Haswell driver pins (crocus / i965)",
                "Configure runtime prefix & DXVK 1.10.3 / WineD3D OpenGL",
                "Extract application icon and register desktop launcher"
            ]
        };
    }

    Rectangle {
        anchors.fill: parent
        radius: 14
        color: "#CC0F172A"
        border.width: 1
        border.color: "#59FFFFFF"

        ColumnLayout {
            anchors.fill: parent
            anchors.margins: 22
            spacing: 14

            RowLayout {
                Layout.fillWidth: true
                spacing: 10

                Rectangle {
                    radius: 8
                    color: "#3338BDF8"
                    border.width: 1
                    border.color: "#8038BDF8"
                    implicitWidth: tagLabel.implicitWidth + 18
                    implicitHeight: 28

                    Text {
                        id: tagLabel
                        anchors.centerIn: parent
                        text: root.planData.platform_tag || "[App]"
                        color: "#38BDF8"
                        font.bold: true
                        font.pixelSize: 13
                    }
                }

                Text {
                    text: root.planData.app_name || "KiteBridge Application"
                    color: "#F8FAFC"
                    font.bold: true
                    font.pixelSize: 18
                    Layout.fillWidth: true
                    elide: Text.ElideRight
                }
            }

            Text {
                text: "Handler: " + (root.planData.handler || "auto") +
                      (root.planData.dxvk_version ? ("  •  DXVK " + root.planData.dxvk_version) : "")
                color: "#94A3B8"
                font.pixelSize: 12
            }

            Rectangle {
                Layout.fillWidth: true
                Layout.fillHeight: true
                radius: 10
                color: "#661E293B"
                border.width: 1
                border.color: "#26FFFFFF"

                ListView {
                    anchors.fill: parent
                    anchors.margins: 12
                    spacing: 8
                    clip: true
                    model: root.planData.steps || []

                    delegate: RowLayout {
                        required property string modelData
                        width: ListView.view.width
                        spacing: 8
                        Text {
                            text: "•"
                            color: "#38BDF8"
                            font.pixelSize: 14
                        }
                        Text {
                            text: modelData
                            color: "#E2E8F0"
                            font.pixelSize: 13
                            wrapMode: Text.WordWrap
                            Layout.fillWidth: true
                        }
                    }
                }
            }

            RowLayout {
                Layout.fillWidth: true
                spacing: 10
                Item { Layout.fillWidth: true }
                Button {
                    text: "Cancel"
                    onClicked: Qt.quit()
                }
                Button {
                    text: "Install & Register"
                    highlighted: true
                    onClicked: Qt.quit()
                }
            }
        }
    }
}
