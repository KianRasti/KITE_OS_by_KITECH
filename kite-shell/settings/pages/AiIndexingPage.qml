import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../components"
import "../theme"

ScrollView {
    id: page
    property var hwProfile: ({})

    property string selectedProvider: "offline"
    property int tokenBudget: 400
    property int sessionTokensUsed: 0
    property string kiteIgnoreText: ".ssh/\n.gnupg/\n.env\n.env.*\n.mozilla/firefox/\n.config/chromium/"

    clip: true

    ColumnLayout {
        width: page.availableWidth
        spacing: 10

        GlassCard {
            title: "BYOK Cloud Provider & Keyring Vault"
            subtitle: "Zero-idle-RAM socket activation (kite-aid.socket) — API keys stored in Linux kernel keyring"

            RowLayout {
                Layout.fillWidth: true
                spacing: 8
                Text {
                    text: "Provider"
                    color: StudioTheme.textPrimary
                    font.pixelSize: 12
                }
                ComboBox {
                    id: providerBox
                    model: ["offline", "gemini", "openai", "anthropic", "groq", "openrouter"]
                    currentIndex: 0
                    onActivated: page.selectedProvider = currentText
                }
            }

            TextField {
                id: apiKeyInput
                Layout.fillWidth: true
                placeholderText: "Masked BYOK API Key (stored in SecretStore)"
                echoMode: TextInput.Password
            }
        }

        GlassCard {
            title: "Sub-400 Token Cloud Budget & Session Telemetry"
            subtitle: "Default 400 input tokens using F1..F10 path aliasing and SimHash deduplication"

            GlassSlider {
                label: "Max Input Token Budget"
                fromValue: 150
                toValue: 800
                stepSize: 10
                value: page.tokenBudget
                valueText: page.tokenBudget + " tokens"
                onMovedValue: function(v) {
                    page.tokenBudget = Math.round(v)
                }
            }

            Text {
                text: "Session Tokens Used: " + page.sessionTokensUsed + " | Estimated Cost: $" + (page.sessionTokensUsed * 0.00000015).toFixed(6)
                color: StudioTheme.accentColor
                font.pixelSize: 12
            }
        }

        GlassCard {
            title: ".kiteignore Privacy Guardrail"
            subtitle: "Blocked before disk content extraction"

            TextArea {
                Layout.fillWidth: true
                implicitHeight: 110
                text: page.kiteIgnoreText
                color: StudioTheme.textPrimary
                onTextChanged: page.kiteIgnoreText = text
            }
        }
    }
}
