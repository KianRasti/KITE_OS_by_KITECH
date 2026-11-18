import QtQuick
import Quickshell
import Quickshell.Widgets

Item {
    id: iconRoot
    property string iconName: ""
    property string fallbackLabel: "A"

    implicitWidth: 28
    implicitHeight: 28

    readonly property string resolvedPath: iconName.length > 0 ? Quickshell.iconPath(iconName, true) : ""

    IconImage {
        anchors.fill: parent
        visible: iconRoot.resolvedPath.length > 0
        source: iconRoot.resolvedPath
    }

    Rectangle {
        anchors.fill: parent
        visible: iconRoot.resolvedPath.length === 0
        radius: 7
        color: Qt.rgba(1, 1, 1, 0.14)
        Text {
            anchors.centerIn: parent
            text: iconRoot.fallbackLabel.length > 0 ? iconRoot.fallbackLabel.charAt(0).toUpperCase() : "A"
            color: "#F8FAFC"
            font.pixelSize: 13
            font.weight: Font.Bold
        }
    }
}
