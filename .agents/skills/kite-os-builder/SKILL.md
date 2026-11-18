---
name: kite-os-builder
description: >-
  Build, configure, preview, and verify KITE_OS for the HP EliteBook Folio 9480m.
  Use this skill when working on the archiso profile, kite-hw-tune hardware profiler,
  Windows 11 Glass UI shell (kite-shell), KiteBridge app dispatchers (.exe, .apk, .dmg),
  or building/testing the bootable ISO from Windows via WSL2, Docker, QEMU, or GitHub Actions.
---

# KITE_OS Builder & Verification Runbook

Procedural workflow for building, previewing, and testing KITE_OS targeting the HP EliteBook Folio 9480m.

## 1. Repository Layout
- `iso-profile/` — `archiso` profile, CachyOS `x86-64-v3` pacman config, package lists, and kernel cmdline defaults.
- `kite-hw-tune/` — Boot-time & udev hardware profiler (`4GB`/`8GB`/`16GB` RAM tiers, `zram`, SSD/HDD I/O scheduler, `i915`, `thermald`).
- `kite-shell/` — Hyprland Floating-First Glass config, Quickshell QML Win11 UI, `kite-settings`, and `preview/` interactive simulator.
- `kite-bridge/` — Unified MIME dispatcher and setup scripts for Wine+`ntsync`+DXVK 1.10.3, Waydroid multi-window, Darling, `apfs-fuse`/`darling-dmg`, and OSX-KVM bridge.
- `installer/` — Calamares Glass theme and Btrfs `zstd:1` partition layout.
- `scripts/` — Windows/WSL2/Docker ISO build scripts and QEMU hardware-emulation test runners.

## 2. Building the Bootable ISO from Windows
1. Ensure WSL2 (Arch/Ubuntu) or Docker Desktop is running with privileged loop-mount support (`--privileged`) for `mkarchiso`.
2. Run the repo ISO builder script (`scripts/build-iso.ps1` or `scripts/build-iso.sh`) to generate `out/kite-os-folio9480-x86_64_v3.iso`.
3. Alternatively, push to GitHub to trigger `.github/workflows/build-iso.yml` and download the built `.iso` artifact.

## 3. Verifying in QEMU (Haswell Simulation)
Emulate the HP Folio 9480m constraints before flashing to USB:
- Pass Haswell CPU flags (`-cpu Haswell-noTSX`) and test each RAM tier (`-m 4G`, `-m 8G`, `-m 16G`).
- Verify `kite-hw-tune` selects the expected `zram` ratio, `vm.swappiness`, I/O scheduler, and Glass blur tier (`systemctl status kite-hw-tune`).
- Verify `/dev/ntsync` and `binder_linux` modules load cleanly (`ls -l /dev/ntsync /dev/binder*`).
- Verify Mesa reports `crocus` (OpenGL) and `anv` (Vulkan 1.2) and VA-API reports `i965`.

## 4. Verifying `KiteBridge` Runtimes
- **Windows**: Confirm `DXVK_VER=1.10.3` (never 2.x+) inside the Wine prefix and validate `ntsync` usage via `WINEDEBUG=+ntsync` or kernel fd checks.
- **Android**: Confirm `waydroid prop get persist.waydroid.multi_windows` returns `true` and Waydroid cgroup pauses when idle on 4 GB / 8 GB tiers.
- **macOS**: Confirm `.dmg` / APFS mounts via `darling-dmg` / `apfs-fuse` and check KVM availability (`/dev/kvm`) before invoking tier-2 GUI forwarding.
