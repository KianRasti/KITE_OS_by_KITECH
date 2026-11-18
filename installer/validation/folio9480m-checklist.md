# HP EliteBook Folio 9480m — Hardware Validation Checklist

**Target OS**: KITE_OS 1.0 (Arch Linux / CachyOS `x86-64-v3`)
**Hardware Target**: HP EliteBook Folio 9480m (4th Gen Intel Haswell ULT, Intel HD Graphics 4400 GT2)
**Automated Gate**: `sudo /usr/local/bin/kite-validate-hardware` (installed from `installer/validation/validate-hardware.sh`; supports `--json`)

---

## 1. System Identification & Firmware Pre-Flight

- [ ] **DMI Product Match**: `sudo dmidecode -s system-product-name` returns `HP EliteBook Folio 9480m`.
- [ ] **CPU SKU & ISA**: `lscpu` identifies Haswell ULT (`i5-4210U`, `i5-4310U`, or `i7-4600U`) with `avx2`, `fma`, `aes`, and `vmx` flags present.
- [ ] **UEFI Boot Mode**: `[ -d /sys/firmware/efi ]` succeeds; VT-x and VT-d enabled in HP BIOS Setup.
- [ ] **Kernel & Parameters**: `uname -r` shows `linux-cachyos`; `/proc/cmdline` contains `i915.enable_fbc=1`, `i915.fastboot=1`, `intel_pstate=active`, and `psi=1`.

---

## 2. USB Boot, Calamares Glass Installer & Btrfs Layout

- [ ] **ISO Integrity**: Verified `.iso` SHA-256 checksum prior to flashing USB media (`dd` / Ventoy / Rufus DD mode).
- [ ] **Live USB Boot**: Boots cleanly to live Hyprland + Quickshell desktop (`i915.fastboot=1` flicker-free handoff) at native `1366x768` or `1600x900` 60 Hz.
- [ ] **Calamares Glass UI**: Installer launches with Aero Blue (`#38BDF8`) Glass theme, readable contrast, and 4-slide `show.qml` slideshow.
- [ ] **Automated Btrfs Partitioning & Subvolumes**: Verify `findmnt -t btrfs` after installation:
  - [ ] `/@` mounted at `/` with `compress=zstd:1,noatime`
  - [ ] `/@home` mounted at `/home` with `compress=zstd:1,noatime`
  - [ ] `/@kitebridge` mounted at `/var/lib/kitebridge` with `compress=zstd:1,noatime`
  - [ ] `/@snapshots` mounted at `/.snapshots` with `compress=zstd:1,noatime`
  - [ ] ESP mounted at `/boot/efi` (`umask=0077`), GRUB bootloader ID `kite-os` present in `efibootmgr -v`.

---

## 3. Automated Validation Script Gate

- [ ] Run `sudo /usr/local/bin/kite-validate-hardware` -> exits `0` with all checks `[PASS]`.
- [ ] Run `sudo /usr/local/bin/kite-validate-hardware --json` -> `summary.failed == 0`, `ram_tier` matches installed DDR3L capacity.
- [ ] Verify `/etc/environment.d/10-kite-haswell.conf` pins `MESA_LOADER_DRIVER_OVERRIDE=crocus` and `LIBVA_DRIVER_NAME=i965`.
- [ ] Verify `glxinfo -B` reports `crocus` (`Intel(R) HD Graphics 4400`), `vainfo` reports `i965`, and `vulkaninfo --summary` reports `anv` at Vulkan `1.2`.
- [ ] Verify `/dev/ntsync` and `/dev/binder*` kernel devices exist and `systemctl is-active kite-hw-tune.service kite-power.service` both return `active`.

---

## 4. Peripheral & Subsystem Verification Matrix

| Subsystem | Driver / Stack | Verification Command(s) | Pass Criteria | Checked |
|---|---|---|---|---|
| **Intel Wireless 7260** | `iwlwifi` | `lspci -k \| grep -A3 Network`, `nmcli dev wifi list`, `iw dev wlan0 get power_save` | 2.4 GHz & 5 GHz associate cleanly; power save toggles on AC vs Battery | [ ] |
| **Bluetooth (Intel 7260)** | `btusb` | `lsusb \| grep 8087:07dc`, `systemctl is-active bluetooth`, `bluetoothctl scan on` | Device discovered and PipeWire A2DP headset audio pairs cleanly | [ ] |
| **Intel I218-LM Ethernet** | `e1000e` | `lspci -k \| grep -A3 Ethernet`, `ethtool <iface>` | Negotiates `1000Mb/s` Full Duplex, DHCP lease succeeds, recovers after S3 sleep | [ ] |
| **Synaptics LuxPad & Stick** | `psmouse` / `libinput` | `libinput list-devices` | 2-finger scroll, tap-to-click, palm rejection, clickpad buttons, trackpoint middle-scroll work; responsive post-resume | [ ] |
| **IDT 92HD91BXX HD Audio** | `snd_hda_intel` + PipeWire | `aplay -l`, `wpctl status`, `cat /sys/module/snd_hda_intel/parameters/power_save` | Speakers, 3.5mm jack auto-switch, internal mic work; `0` on AC, `1` on Battery with zero audible pop | [ ] |
| **Validity VFS495 Fingerprint** | USB `138a:003f` / `fprintd` | `lsusb \| grep 138a:003f`, `fprintd-list "$USER"` | USB sensor enumerated (`138a:003f`); enrollment/verification checked against installed `libfprint` build | [ ] |
| **DisplayPort 1.2 + VGA** | `i915` + Hyprland | `hyprctl monitors`, plug DP + VGA monitors simultaneously | `eDP-1` + `DP-1` (up to 4K@60Hz / 1080p@60Hz) + `VGA-1` (1080p@60Hz) hotplug, extended workspaces, and DP audio sink work | [ ] |
| **Backlight, Fn Keys & S3** | `intel_backlight` + `thermald` | `brightnessctl info`, close lid 10s, `systemctl is-active thermald`, `sensors` | Smooth brightness steps, Fn keys work, S3 lid suspend/resume clean, thermal throttling stable | [ ] |

---

## 5. RAM Tier & Storage Scheduler Matrix (4 GB / 8 GB / 16 GB)

Verify `kite-hw-tune` output in `/run/kite-os/hw-profile.json`, `zramctl`, and `/proc/sys/vm/*` for the tested SKU:

- [ ] **4 GB Tier (`< 6144` MB)**:
  - `zramctl`: `150%` RAM size, `lz4` algorithm
  - `sysctl`: `vm.swappiness=180`, `vm.page-cluster=0`, `vm.watermark_boost_factor=0`
  - Glass blur: `static` (`enabled: false`), idle budget `< 260 MB`
  - Waydroid lifecycle: `freeze_then_teardown` (`300` s idle)
- [ ] **8 GB Tier (`6144..12288` MB)**:
  - `zramctl`: `100%` RAM size, `zstd` algorithm
  - `sysctl`: `vm.swappiness=150`, `vm.page-cluster=0`, `vm.vfs_cache_pressure=75`
  - Glass blur: `kawase_2pass` (`size=6, passes=2, xray=true`) on AC -> `kawase_1pass` (`size=4, passes=1`) on Battery, idle budget `~350 MB`
  - Waydroid lifecycle: `cgroup_freeze`
- [ ] **16 GB Tier (`> 12288` MB)**:
  - `zramctl`: `50%` RAM size, `zstd` algorithm
  - `sysctl`: `vm.swappiness=100`, `vm.page-cluster=0`, `vm.dirty_ratio=10`
  - Glass blur: `kawase_full` (`size=6, passes=2, xray=true`) on AC -> `kawase_1pass` on Battery, idle budget `~480 MB`
  - Waydroid lifecycle: `prewarmed`; `osx_kvm.hugepages_on_demand=true`
- [ ] **Storage I/O Scheduler**:
  - SSD / mSATA (`rotational=0`): active `[kyber]` or `[none]` in `/sys/block/<dev>/queue/scheduler`
  - HDD (`rotational=1`): active `[bfq]` in `/sys/block/<dev>/queue/scheduler`

---

## 6. KiteBridge Quick Smoke Verification

- [ ] **Windows**: `kite-bridge inspect sample.exe --json` confirms `dxvk_version: "1.10.3"`, `ntsync: true`, `MESA_LOADER_DRIVER_OVERRIDE=crocus`, and DX12 routed to WineD3D OpenGL 4.6.
- [ ] **Android**: Waydroid multi-window property `persist.waydroid.multi_windows=true` active with `/dev/binder*`.
- [ ] **macOS**: Volume tools (`darling-dmg` / `apfs-fuse`) and `/dev/kvm` availability verified for OSX-KVM Haswell bridge.

---

## 7. Battery Life Measurement Protocol

**Standardized Test Baseline**:
1. Unplug AC adapter; confirm `/run/kite-os/hw-profile.json` reports `"source": "Battery"`, `"epp": "balance_power"`, and Glass auto-simplification active.
2. Set display brightness to `50%` (`brightnessctl set 50%`), Wi-Fi associated (5 GHz), Bluetooth idle (no active audio stream).
3. Wait 5 minutes for power readings to stabilize.

| Workload | Measurement Tool | Target / Observed Power (W) | Estimated Runtime (52 Wh Battery) | Checked |
|---|---|---|---|---|
| **Desktop Idle (Glass active)** | `upower -i /org/freedesktop/UPower/devices/battery_BAT0` / `powertop` | ____ W (target < 6.5 W) | ____ hrs | [ ] |
| **1080p H.264 Playback (`i965` VA-API)** | `mpv --hwdec=vaapi` + `upower -i` | ____ W (target < 9.5 W) | ____ hrs | [ ] |
| **Web Browsing + Light Productivity** | 100% -> 10% real-world drain log | ____ W | ____ hrs | [ ] |

---

## 8. Windows 11 Benchmark Comparison (Same Folio 9480m Unit)

| Metric | Windows 11 (23H2/24H2) | KITE_OS 1.0 | Delta | Checked |
|---|---|---|---|---|
| **Cold Boot to Desktop (s)** | ____ s | ____ s | ____ | [ ] |
| **Idle RAM Usage (MB)** | ____ MB | ____ MB | ____ | [ ] |
| **Desktop Glass UI Frame Rate (FPS)** | ____ fps | ____ fps (60 fps target) | ____ | [ ] |
| **OS Disk Footprint (GB, Btrfs `zstd:1` vs NTFS)** | ____ GB | ____ GB | ____ | [ ] |
| **7-Zip / Geekbench AVX2 Score** | ____ | ____ | ____ | [ ] |
| **1080p H.264 Playback CPU %** | ____ % | ____ % | ____ | [ ] |
| **Idle / Browsing Battery Draw (W & hrs)** | ____ W / ____ hrs | ____ W / ____ hrs | ____ | [ ] |

---

## 9. Tester Sign-Off

- **Unit Serial / Service Tag**: ________________________
- **Installed RAM Tier**: `[ ] 4 GB` `[ ] 8 GB` `[ ] 16 GB`
- **Storage Type**: `[ ] mSATA/SATA SSD (rotational=0)` `[ ] SATA HDD (rotational=1)`
- **Tester Name & Date**: ________________________
- **Overall Result**: `[ ] PASS` `[ ] FAIL (attach kite-validate-hardware --json output)`
