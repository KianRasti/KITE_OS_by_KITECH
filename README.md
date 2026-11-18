# KITE_OS — HP EliteBook Folio 9480m

**KITE_OS** is a custom, hardware-tuned Arch Linux / CachyOS `x86-64-v3` distribution and universal app runtime monorepo engineered specifically for the **HP EliteBook Folio 9480m** (4th Gen Intel Haswell ULT).

## 1. Target Silicon & Hardware Profile

- **CPU**: Intel Core i5-4210U / i5-4310U / i7-4600U (4th Gen Haswell ULT, `x86-64-v3`: AVX2, FMA, BMI1, BMI2)
- **GPU**: Intel HD Graphics 4400 (Haswell GT2)
- **Memory**: 4 GB / 8 GB / 16 GB DDR3L-1600
- **Storage**: mSATA / SATA III SSD (`rotational=0`) or SATA HDD (`rotational=1`)
- **Networking**: Intel Wireless 7260 (`iwlwifi` / `btusb`) & Intel I218-LM Gigabit Ethernet (`e1000e`)
- **Peripherals**: Synaptics LuxPad (`libinput`), IDT 92HD91BXX HD Audio (`snd_hda_intel` + PipeWire), Validity VFS495 (`138a:003f`) fingerprint reader (`fprintd`)

## 2. Monorepo Layout

```text
HP_Folio9480/
├── AGENTS.md                                  # Workspace hardware & architecture invariants
├── .agents/skills/kite-os-builder/SKILL.md    # KITE_OS build, QEMU, CI & KiteBridge runbook
├── README.md                                  # Monorepo overview, invariants & entrypoints
├── pyproject.toml                             # Shared Python 3.12 packaging & pytest config
├── iso-profile/                               # Phase 1: Arch/CachyOS x86-64-v3 archiso profile
│   ├── profiledef.sh
│   ├── pacman.conf
│   ├── packages.x86_64
│   ├── efiboot/                               # systemd-boot entries (Folio 9480m kernel params)
│   ├── grub/                                  # GRUB fallback config
│   ├── syslinux/                              # BIOS syslinux bootloader configs
│   └── airootfs/                              # Live/installed rootfs overlays & first-boot hook
├── scripts/                                   # ISO build, QEMU Haswell test, invariant checks
│   ├── build-iso.sh
│   ├── build-iso.ps1                          # Windows PowerShell 5.1 compatible
│   ├── test-qemu.sh
│   ├── test-qemu.ps1                          # Windows PowerShell 5.1 compatible
│   ├── check_invariants.py                    # Syntax-aware hardware invariant verifier
│   └── tests/                                 # M1 unit & dry-run pytest suite
├── .github/workflows/
│   └── build-iso.yml                          # Validation + privileged Archiso ISO build CI
├── kite-hw-tune/                              # Phase 2: Dynamic RAM/storage/power auto-tuner
├── kite-shell/                                # Phase 3: Hyprland Floating-First + Quickshell + kite-settings
│   └── preview/                               # Static interactive browser simulator
├── kite-bridge/                               # Phase 4: Universal CLI/MIME runtime (Wine, Waydroid, macOS)
├── installer/                                 # Phase 5: Calamares Glass UI theme, Btrfs & validation
└── tests/e2e/                                 # Opaque-box E2E test suite (Tiers 1-5)
```

## 3. Hardware Invariants

| Subsystem | Mandatory Configuration | Strictly Prohibited |
|---|---|---|
| **CPU / ISA** | Arch/CachyOS `x86-64-v3` (`[cachyos-v3]`, `[cachyos-core-v3]`, `[cachyos-extra-v3]`), `-march=x86-64-v3` / `-march=haswell`, QEMU `-cpu Haswell-noTSX` (`+invtsc,vendor=GenuineIntel` for OSX-KVM) | Generic-only downgrade when `x86-64-v3` exists |
| **OpenGL / Vulkan** | Mesa `crocus` (`MESA_LOADER_DRIVER_OVERRIDE=crocus`), `anv` Vulkan 1.2 max | Prohibited (do NOT use `iris` / `MESA_LOADER_DRIVER_OVERRIDE=iris` / `mesa-iris`) |
| **VA-API Video** | `libva-intel-driver` (`LIBVA_DRIVER_NAME=i965`) | Prohibited (do NOT use `intel-media-driver` / `LIBVA_DRIVER_NAME=iHD`) |
| **DirectX / Wine** | `linux-cachyos` `/dev/ntsync`, **DXVK pinned to `1.10.3`** (`d3d9`, `d3d10core`, `d3d11`, `dxgi`), DX12 -> WineD3D OpenGL 4.6 (`crocus`) | Prohibited (never `DXVK 2.0+` — requires Vulkan 1.3; never `VKD3D-Proton` / `vkd3d-proton`) |
| **Glass Blur Budget** | 2-pass Dual-Kawase (`size=6, passes=2, xray=true`) on AC; 1-pass on `8G`/`16G` battery; static acrylic on `4G` | Unbounded multi-pass blur exceeding HD 4400 frame budget |
| **Storage & Btrfs** | Btrfs `compress=zstd:1,noatime` with `@`, `@home`, `@kitebridge`, `@snapshots`; `kyber`/`none` (`rotational == 0`) vs `bfq` (`rotational == 1`) | Hardcoded single disk scheduler |
| **RAM Tiers** | `4G`: `zram` 150% `lz4`, `vm.swappiness=180`; `8G`: `zram` 100% `zstd`, `vm.swappiness=150`; `16G`: `zram` 50% `zstd`, `vm.swappiness=100` | Single-SKU hardcoded RAM tuning |

## 4. ISO Build Workflow

- **Windows (Docker `--privileged` or WSL2)**:
  ```powershell
  .\scripts\build-iso.ps1 -Mode Auto
  .\scripts\build-iso.ps1 -Mode Docker -DryRun
  .\scripts\build-iso.ps1 -Mode WSL -DryRun
  ```
- **Linux / WSL2 / Docker Container**:
  ```bash
  ./scripts/build-iso.sh
  ./scripts/build-iso.sh --dry-run --json
  ```
- **Output Artifact**: `out/kite-os-folio9480-x86_64_v3.iso` and `out/kite-os-folio9480-x86_64_v3.iso.sha256`
- **CI Pipeline**: `.github/workflows/build-iso.yml` runs `validate` (invariants, pytest, Bash/PowerShell syntax, dry-runs) followed by `build-iso` inside `archlinux:latest` (`--privileged`) uploading the `.iso` and `.sha256` artifacts.

## 5. QEMU Haswell Emulation Workflow

Emulate the HP EliteBook Folio 9480m (`-cpu Haswell-noTSX`, `-smp 4,cores=2,threads=2`, OVMF UEFI, `e1000e` NIC, `intel-hda`) across all SKU RAM and storage configurations:

- **Windows PowerShell 5.1**:
  ```powershell
  .\scripts\test-qemu.ps1 -Ram 4G -Rotational 0
  .\scripts\test-qemu.ps1 -Ram 8G -Rotational 1 -DryRun -Json
  .\scripts\test-qemu.ps1 -Ram 16G -Rotational 0 -Headless
  ```
- **Linux / Git Bash**:
  ```bash
  ./scripts/test-qemu.sh --ram 8G --rotational 0
  ./scripts/test-qemu.sh --ram 4G --rotational 1 --dry-run --json
  ```

## 6. Local UI Preview (`kite-shell/preview/`)

Serve the zero-build interactive Glass UI simulator locally:

```powershell
C:\Python312\python.exe -m http.server 8080 -d kite-shell/preview
```

Open `http://127.0.0.1:8080` to test centered/left taskbar alignment, Start Menu (`[Win]`/`[Android]`/`[macOS]` tags), `Win+A` Quick Settings, `Win+N` Notifications & Calendar, `Win+Z` Snap Layouts, `4G`/`8G`/`16G` + AC/Battery hardware simulation, and live `kite-settings` Glass controls.

## 7. Windows-Host Test, Invariant & Lint Entrypoints

- **Python Unit & E2E Tests** (always invoke `C:\Python312\python.exe`, never bare `pytest` or `python3`):
  ```powershell
  C:\Python312\python.exe -m pytest scripts/tests -v
  C:\Python312\python.exe -m pytest kite-hw-tune/tests -v
  C:\Python312\python.exe -m pytest kite-shell/tests -v
  C:\Python312\python.exe -m pytest kite-bridge/tests -v
  C:\Python312\python.exe -m pytest installer/tests -v
  C:\Python312\python.exe -m pytest tests/e2e -m tier1
  ```
  > **Note on cross-module root `pytest` collection**: `kite-bridge/tests` imports `from tests.conftest import ...`, which collides with `kite-hw-tune/tests/conftest.py` when running root `pytest` across all modules simultaneously (`kite-hw-tune` precedes `kite-bridge` in root `pyproject.toml` `pythonpath`). Run `kite-bridge/tests` via `C:\Python312\python.exe -m pytest kite-bridge/tests -v` (which scopes to `kite-bridge/pyproject.toml`).
- **Repository Invariant Checker**:
  ```powershell
  C:\Python312\python.exe scripts/check_invariants.py --scope auto --json
  C:\Python312\python.exe scripts/check_invariants.py --scope m1 --json
  ```
- **PowerShell 5.1 Syntax Check**:
  ```powershell
  Get-ChildItem scripts -Filter *.ps1 | ForEach-Object {
    $t = $null; $e = $null
    $null = [System.Management.Automation.Language.Parser]::ParseFile($_.FullName, [ref]$t, [ref]$e)
    if ($e.Count -gt 0) { throw "Parse error in $($_.Name)" }
  }
  ```
- **Git Bash Syntax Check** (never bare `bash`):
  ```powershell
  & "C:\Program Files\Git\bin\bash.exe" -n scripts/build-iso.sh
  & "C:\Program Files\Git\bin\bash.exe" -n scripts/test-qemu.sh
  ```
- **JS / YAML / JSON / QML / Preview Checks**:
  - `node --check kite-shell/preview/app.js`
  - `C:\Python312\python.exe -c "import yaml; yaml.safe_load(open('.github/workflows/build-iso.yml', encoding='utf-8'))"`
  - `C:\Python312\python.exe -m playwright` (headless Chromium verification of `kite-shell/preview/`)
