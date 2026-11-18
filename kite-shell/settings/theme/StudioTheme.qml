pragma Singleton

import QtQuick

QtObject {
    id: theme

    property color accentColor: "#38BDF8"
    property color surfaceTint: "#0F172A"
    property real transparency: 0.72
    property int cornerRadius: 12
    property real specularBrightness: 0.35
    property real animationSpeed: 1.0

    readonly property color panelBackground: Qt.rgba(surfaceTint.r, surfaceTint.g, surfaceTint.b, Math.max(0.45, Math.min(0.98, transparency + 0.14)))
    readonly property color cardBackground: Qt.rgba(1, 1, 1, 0.06)
    readonly property color cardBorder: Qt.rgba(1, 1, 1, Math.max(0.08, specularBrightness * 0.45))
    readonly property color specularBorder: Qt.rgba(1, 1, 1, Math.max(0.12, specularBrightness))
    readonly property color textPrimary: "#F8FAFC"
    readonly property color textSecondary: "#94A3B8"
    readonly property color warningAmber: "#F59E0B"
    readonly property color dangerRed: "#EF4444"
    readonly property color successEmerald: "#10B981"
    readonly property int animMs: animationSpeed <= 0 ? 0 : Math.max(60, Math.round(180 / animationSpeed))
}
