# KITE_OS Workspace Rules (HP EliteBook Folio 9480m)

All code, kernel configs, packages, UI shell definitions, and scripts in this repository target **KITE_OS** for the **HP EliteBook Folio 9480m** (4th Gen Intel Haswell ULT). Follow these hardware and architectural invariants strictly:

## 1. Base System & CPU Target
- **Base Distribution**: Arch Linux / CachyOS `x86-64-v3` (`archiso` build pipeline).
- **Compiler & Repo Optimization**: Leverage Haswell `AVX2`, `FMA`, `BMI1`, and `BMI2` (`-march=x86-64-v3` / `-march=haswell` for locally compiled components); never downgrade core runtimes to generic `x86-64` builds when `x86-64-v3` packages exist.
- **Filesystem**: Btrfs with `compress=zstd:1,noatime` and subvolumes (`@`, `@home`, `@kitebridge`, `@snapshots`).

## 2. Intel HD Graphics 4400 (Haswell GT2) Constraints
- **OpenGL Driver**: Always target Mesa **`crocus`** (`MESA_LOADER_DRIVER_OVERRIDE=crocus`). Do NOT configure `iris` (Broadwell/Gen8+ only).
- **VA-API Video Decode**: Always target `libva-intel-driver` (**`i965`**). Do NOT use `intel-media-driver` (`iHD`, Broadwell+ only).
- **Vulkan Ceiling (Critical)**: Intel HD 4400 (`anv` Haswell driver) supports **Vulkan 1.2 maximum**.
  - **DXVK must be pinned to `1.10.3`** (DXVK 2.0+ requires Vulkan 1.3 `VK_EXT_graphics_pipeline_library` and will fail on this GPU).
  - DirectX 12 workloads must fall back cleanly to WineD3D OpenGL 4.6 (`crocus`), not VKD3D-Proton.

## 3. Dynamic Hardware Scaling (`kite-hw-tune`)
Never hardcode single-machine RAM or disk assumptions. All tuning scripts and services must scale dynamically across all HP Folio 9480m SKUs:
- **4 GB RAM**: `zram` at 150% RAM (`lz4`), `vm.swappiness=180`, static-cached acrylic blur, strict on-demand Wine/Waydroid teardown after idle. Target `< 260 MB` idle RAM.
- **8 GB RAM**: `zram` at 100% RAM (`zstd`), `vm.swappiness=150`, live 2-pass Dual-Kawase blur @ 60fps on AC (1-pass on battery), cgroup-frozen idle Waydroid. Target `~350 MB` idle RAM.
- **16 GB RAM**: `zram` at 50% RAM (`zstd`), `vm.swappiness=100`, pre-warmed Wine/Waydroid daemons, on-demand KVM hugepages for macOS GUI bridge.
- **Storage**: Dynamically assign `none`/`kyber` scheduler when `/sys/block/*/queue/rotational == 0` (mSATA/SATA SSD) and `bfq` when `rotational == 1` (HDD).

## 4. Windows 11 Glass UI Shell (`kite-shell`)
- **Compositor & Shell**: Hyprland in **Floating-First (Windows 11) Mode** + **Quickshell (Qt6/QML Wayland layer-shell)** + `kite-settings`.
- **60fps GPU Budget**: Keep Intel HD 4400 glass blur bounded to **2-pass downsampled Dual-Kawase (`size=6, passes=2, xray=true`)** on AC and automatic 1-pass/flat fallback on battery or 4 GB RAM tier.
- **UX Parity & Customization**: Maintain Windows 11 interaction flows (centered/left taskbar toggle, Start Menu, Win+A Quick Settings, Win+N Notifications, Win+Z Snap Layouts) and expose transparency, blur radius, tint presets, corner radius, and animation physics in `kite-settings`.

## 5. `KiteBridge` Universal App & File Runtime
- **Windows (`.exe`, `.msi`, `.bat`)**: Wine-CachyOS / Proton-GE + kernel **`ntsync`** (`/dev/ntsync`) + **DXVK 1.10.3**.
- **Android (`.apk`, `.aab`)**: **Waydroid** in multi-window Wayland mode (`persist.waydroid.multi_windows=true`) + `binder_linux` + `libndk`/`libhoudini`.
- **macOS (`.dmg`, `.pkg`, `.app`, APFS/HFS+)**:
  - Mount `.dmg`, HFS+, and APFS natively via `darling-dmg`, `hfsprogs`, and `apfs-fuse`.
  - Run CLI/Mach-O binaries natively via **Darling**.
  - Launch full Cocoa GUI `.app` bundles via an **on-demand OSX-KVM Haswell passthrough bridge** (`-cpu Haswell-noTSX,+invtsc,vendor=GenuineIntel`) with seamless window forwarding and auto-hibernate when idle.

## 6. Kite AI Local Data Mining & BYOK Cloud Agent (`kite-ai`)
- **Zero Idle Daemon Footprint**: Run strictly via on-demand systemd socket activation (`kite-aid.socket`) and idle-scheduled indexing (`kite-index.timer`, `ionice -c 3`) backed by embedded SQLite FTS5 (`bm25` + `trigram`) — never enable `kite-aid.service` as a persistent boot daemon.
- **Privacy Guardrail**: Filter out `.ssh`, `.gnupg`, `.env*`, browser profiles, and `/etc/shadow` via `.kiteignore` before reading disk content.
- **Sub-400 Token Cloud Budget**: Compute 64-bit SimHash deduplication (Hamming distance <= 3) and 25-word TF-IDF/TextRank fingerprints locally; default BYOK cloud calls to `<= 400` input tokens using `F1..F10` path aliasing and static `SYSTEM_PREFIX` prompt caching, and force Tier 0 zero-token local search on `4G` Battery.

