from __future__ import annotations

from pathlib import Path

from scripts.tests.m1_helpers import REPO_ROOT

ISO_DIR = REPO_ROOT / "iso-profile"


def test_profiledef_bootmodes_and_permissions() -> None:
    text = (ISO_DIR / "profiledef.sh").read_text(encoding="utf-8")
    assert 'iso_name="kite-os-folio9480"' in text
    assert "bios.syslinux" in text
    assert "uefi.systemd-boot" in text
    # mkarchiso aborts if both uefi.systemd-boot and uefi.grub are in bootmodes
    bootmodes_line = [ln for ln in text.splitlines() if ln.startswith("bootmodes=")][0]
    assert "uefi.grub" not in bootmodes_line
    assert '["/etc/sudoers.d"]="0:0:750"' in text
    assert '["/etc/sudoers.d/10-kite-wheel"]="0:0:440"' in text


def test_pacman_conf_cachyos_v3_before_arch_repos() -> None:
    lines = (ISO_DIR / "pacman.conf").read_text(encoding="utf-8").splitlines()
    active_text = "\n".join(ln.split("#", 1)[0].strip() for ln in lines if ln.split("#", 1)[0].strip())
    assert "Architecture = x86_64 x86_64_v3" in active_text
    for repo in ("[cachyos-v3]", "[cachyos-core-v3]", "[cachyos-extra-v3]", "[cachyos]", "[core]", "[extra]", "[multilib]"):
        assert repo in active_text
    assert active_text.index("[cachyos-v3]") < active_text.index("[core]")
    assert active_text.index("[cachyos-core-v3]") < active_text.index("[core]")
    assert active_text.index("[cachyos-extra-v3]") < active_text.index("[core]")


def test_packages_x86_64_haswell_and_repo_only() -> None:
    lines = (ISO_DIR / "packages.x86_64").read_text(encoding="utf-8").splitlines()
    tokens: set[str] = set()
    for line in lines:
        cleaned = line.split("#", 1)[0].strip()
        tokens.update(cleaned.split())
    required = {
        "linux-cachyos",
        "mesa",
        "lib32-mesa",
        "vulkan-intel",
        "lib32-vulkan-intel",
        "libva-intel-driver",
        "pipewire",
        "btrfs-progs",
        "zram-generator",
        "networkmanager",
        "bluez",
        "thermald",
        "fprintd",
        "hyprland",
        "quickshell",
        "wine-cachyos",
        "waydroid",
        "cachyos-calamares",
        "python",
        "python-pip",
        "python-setuptools",
        "python-yaml",
    }
    assert required <= tokens
    forbidden = {"intel-media-driver", "python-validity", "hfsprogs", "apfs-fuse", "darling", "darling-dmg"}
    assert tokens.isdisjoint(forbidden)


def test_mirrorlists_use_literal_x86_64_v3() -> None:
    v3_ml = (ISO_DIR / "airootfs" / "etc" / "pacman.d" / "cachyos-v3-mirrorlist").read_text(encoding="utf-8")
    assert "x86_64_v3" in v3_ml
    assert "$arch_v3" not in v3_ml


def test_no_windows_symlink_stubs_in_multi_user_wants() -> None:
    wants_dir = ISO_DIR / "airootfs" / "etc" / "systemd" / "system" / "multi-user.target.wants"
    assert not wants_dir.exists(), "multi-user.target.wants symlinks must be created at build time on Linux FS"


def test_customize_airootfs_uses_unified_staging_path() -> None:
    script = (ISO_DIR / "airootfs" / "root" / "customize_airootfs.sh").read_text(encoding="utf-8")
    assert 'SRC_ROOT="/opt/kite-os-src"' in script
    for comp in ("kite-hw-tune", "kite-shell", "kite-bridge", "installer"):
        assert comp in script
