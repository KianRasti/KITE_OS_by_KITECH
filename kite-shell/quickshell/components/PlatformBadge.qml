import QtQuick

Rectangle {
    id: badge
    property string platform: "linux"

    visible: platform !== "linux"
    implicitWidth: labelItem.implicitWidth + 10
    implicitHeight: 18
    radius: 5

    color: {
        if (platform === "win") return Qt.rgba(0.22, 0.74, 0.97, 0.22)
        if (platform === "android") return Qt.rgba(0.06, 0.73, 0.51, 0.22)
        if (platform === "macos") return Qt.rgba(0.80, 0.84, 0.90, 0.22)
        return "transparent"
    }
    border.width: 1
    border.color: {
        if (platform === "win") return "#38BDF8"
        if (platform === "android") return "#10B981"
        if (platform === "macos") return "#CBD5E1"
        return "transparent"
    }

    Text {
        id: labelItem
        anchors.centerIn: parent
        text: {
            if (badge.platform === "win") return "[Win]"
            if (badge.platform === "android") return "[Android]"
            if (badge.platform === "macos") return "[macOS]"
            return ""
        }
        color: "#F8FAFC"
        font.pixelSize: 10
        font.weight: Font.Bold
    }
}
