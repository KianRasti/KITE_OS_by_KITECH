from __future__ import annotations

from conftest import CHECKLIST_FILE


def test_checklist_exists_and_covers_all_hardware_sections():
    assert CHECKLIST_FILE.is_file()
    raw = CHECKLIST_FILE.read_bytes()
    assert b"\r\n" not in raw, "folio9480m-checklist.md must use LF line endings"
    text = raw.decode("utf-8")
    assert "- [ ]" in text

    required_tokens = [
        "Folio 9480m",
        "USB",
        "7260",
        "iwlwifi",
        "btusb",
        "I218-LM",
        "e1000e",
        "Synaptics LuxPad",
        "92HD91BXX",
        "VFS495",
        "DisplayPort 1.2",
        "VGA",
        "4 GB",
        "8 GB",
        "16 GB",
        "Battery",
        "Windows 11",
        "validate-hardware.sh",
        "@kitebridge",
        "@snapshots",
        "compress=zstd:1,noatime",
        "crocus",
        "i965",
        "1.10.3",
    ]
    for token in required_tokens:
        assert token in text, f"Checklist missing required hardware/validation item: {token}"
