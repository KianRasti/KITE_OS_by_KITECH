"""Shared opaque-box E2E harness, fixtures, and validators for KITE_OS."""
from __future__ import annotations

import base64
import functools
import http.server
import json
import os
import re
import shutil
import socketserver
import subprocess
import sys
import threading
from pathlib import Path
from typing import Any, Callable

import jsonschema
import pytest
import yaml

# Canonical verbatim SHA-256 hashes & byte lengths from PROJECT.md §8
AGENTS_SHA256 = "2c9c5fc4dc8353e4ba91c7c99c798b7db4603f6cefc882295dc5e966a3169de5"
AGENTS_BYTES = 4526
AGENTS_LINES = 41

SKILL_SHA256 = "639c61b21082ebca9dcd44c95bcf075876a1ec654f94b24ed7a2168e8056ba8b"
SKILL_BYTES = 2781
SKILL_LINES = 37

ISO_FILENAME = "kite-os-folio9480-x86_64_v3.iso"

# Prohibitory prose indicators so doc/test scans don't false-positive on warnings
PROHIBITORY_MARKERS = (
    "never",
    "not",
    "do not",
    "don't",
    "avoid",
    "must not",
    "forbid",
    "prohibit",
    "instead of",
    "black-screen",
    "will fail",
    "reject",
    "zero active",
    "broadwell",
)

# JSON Schema v1 for /run/kite-os/hw-profile.json (PROJECT.md §1)
HW_PROFILE_SCHEMA_V1: dict[str, Any] = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "required": [
        "schema_version",
        "ram_mb",
        "memory",
        "power",
        "blur",
        "storage",
        "subsystems",
    ],
    "properties": {
        "schema_version": {"const": 1},
        "ram_mb": {"type": "integer", "minimum": 1},
        "memory": {
            "type": "object",
            "required": [
                "tier",
                "zram_percent",
                "zram_size_mb",
                "zram_algo",
                "idle_budget_mb",
                "sysctl",
            ],
            "properties": {
                "tier": {"enum": ["4G", "8G", "16G"]},
                "zram_percent": {"type": "integer", "enum": [50, 100, 150]},
                "zram_size_mb": {"type": "integer", "minimum": 1},
                "zram_algo": {"enum": ["lz4", "zstd"]},
                "idle_budget_mb": {"type": "integer", "minimum": 1},
                "sysctl": {
                    "type": "object",
                    "required": ["vm.swappiness", "vm.page-cluster"],
                    "properties": {
                        "vm.swappiness": {"type": "integer", "minimum": 0, "maximum": 200},
                        "vm.page-cluster": {"type": "integer", "minimum": 0},
                    },
                },
            },
        },
        "power": {
            "type": "object",
            "required": [
                "source",
                "epp",
                "snd_hda_intel_power_save",
                "iwlwifi_power_save",
            ],
            "properties": {
                "source": {"enum": ["AC", "Battery"]},
                "epp": {"type": "string", "minLength": 1},
                "snd_hda_intel_power_save": {"type": "integer", "enum": [0, 1]},
                "iwlwifi_power_save": {"type": "boolean"},
            },
        },
        "blur": {
            "type": "object",
            "required": ["tier", "enabled", "size", "passes", "xray"],
            "properties": {
                "tier": {
                    "enum": ["static", "kawase_1pass", "kawase_2pass", "kawase_full"]
                },
                "enabled": {"type": "boolean"},
                "size": {"type": "integer", "minimum": 0, "maximum": 6},
                "passes": {"type": "integer", "minimum": 0, "maximum": 2},
                "xray": {"type": "boolean"},
            },
        },
        "storage": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["device", "rotational", "scheduler"],
                "properties": {
                    "device": {"type": "string", "minLength": 1},
                    "rotational": {"type": "integer", "enum": [0, 1]},
                    "scheduler": {"enum": ["kyber", "none", "bfq"]},
                },
            },
        },
        "subsystems": {
            "type": "object",
            "required": ["wine", "waydroid", "osx_kvm"],
            "properties": {
                "wine": {
                    "type": "object",
                    "required": ["dxvk_version", "ntsync", "prewarm"],
                    "properties": {
                        "dxvk_version": {"const": "1.10.3"},
                        "ntsync": {"type": "boolean"},
                        "prewarm": {"type": "boolean"},
                    },
                },
                "waydroid": {
                    "type": "object",
                    "required": ["idle_policy", "teardown_after_sec", "prewarm"],
                    "properties": {
                        "idle_policy": {
                            "enum": ["freeze_then_teardown", "cgroup_freeze", "prewarmed"]
                        },
                        "teardown_after_sec": {"type": ["integer", "null"]},
                        "prewarm": {"type": "boolean"},
                    },
                },
                "osx_kvm": {
                    "type": "object",
                    "required": ["hugepages_on_demand"],
                    "properties": {
                        "hugepages_on_demand": {"type": "boolean"},
                    },
                },
            },
        },
    },
}

# JSON Schema v1 for ~/.config/kite-os/settings.json (PROJECT.md §2)
SETTINGS_SCHEMA_V1: dict[str, Any] = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "required": [
        "schema_version",
        "theme_preset",
        "accent_color",
        "taskbar_alignment",
        "transparency",
        "blur_radius",
        "specular_edge_brightness",
        "corner_radius",
        "animation_speed",
        "spring_curve",
        "wallpaper",
        "battery_glass_autosimplify",
        "mitigations_off_requested",
    ],
    "properties": {
        "schema_version": {"const": 1},
        "theme_preset": {
            "enum": [
                "Aero Blue",
                "Frosted Obsidian",
                "Emerald Glass",
                "Sunset Mica",
                "Ultra-Light Flat",
            ]
        },
        "accent_color": {"type": "string", "pattern": r"^#[0-9A-Fa-f]{6}$"},
        "taskbar_alignment": {"enum": ["center", "left"]},
        "transparency": {"type": "number", "minimum": 0.0, "maximum": 1.0},
        "blur_radius": {"type": ["integer", "number"], "minimum": 0, "maximum": 6},
        "specular_edge_brightness": {"type": "number", "minimum": 0.0, "maximum": 1.0},
        "corner_radius": {"type": ["integer", "number"], "minimum": 0},
        "animation_speed": {"type": "number", "exclusiveMinimum": 0.0},
        "spring_curve": {"type": "string", "minLength": 1},
        "wallpaper": {"type": "string", "minLength": 1},
        "battery_glass_autosimplify": {"type": "boolean"},
        "mitigations_off_requested": {"type": "boolean"},
    },
}

# JSON Schema for kite-bridge inspect / open --dry-run --json (PROJECT.md §7)
BRIDGE_INSPECT_SCHEMA: dict[str, Any] = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "required": ["path", "extension", "platform", "handler", "command", "env"],
    "properties": {
        "path": {"type": "string", "minLength": 1},
        "extension": {"type": "string"},
        "platform": {"enum": ["win", "android", "macos"]},
        "handler": {"type": "string", "minLength": 1},
        "command": {"type": "array", "items": {"type": "string"}, "minItems": 1},
        "env": {"type": "object"},
    },
}

_CLI_HELP_CACHE: dict[tuple[str, str], dict[str, Any]] = {}


def pytest_configure(config: pytest.Config) -> None:
    """Register E2E tier markers locally so --collect-only has zero warnings."""
    config.addinivalue_line(
        "markers", "tier1: Category-partition requirement tests (>=5/feature)"
    )
    config.addinivalue_line(
        "markers", "tier2: Boundary, negative, and corner-case tests (>=5/feature)"
    )
    config.addinivalue_line(
        "markers", "tier3: Pairwise cross-feature combination tests"
    )
    config.addinivalue_line(
        "markers", "tier4: Real-world end-to-end workload & Playwright Chromium UI tests"
    )


def get_repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


@pytest.fixture(scope="session")
def repo_root() -> Path:
    return get_repo_root()


@pytest.fixture(scope="session")
def python_exe() -> str:
    preferred = Path(r"C:\Python312\python.exe")
    return str(preferred) if preferred.is_file() else sys.executable


@pytest.fixture(scope="session")
def git_bash_exe() -> str:
    bash = Path(r"C:\Program Files\Git\bin\bash.exe")
    if not bash.is_file():
        pytest.fail(f"Git Bash not found at {bash} (never fall back to bare WSL bash)")
    return str(bash)


@pytest.fixture(scope="session")
def powershell_exe() -> str:
    ps = Path(r"C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe")
    if not ps.is_file():
        pytest.fail(f"Windows PowerShell 5.1 not found at {ps}")
    return str(ps)


@pytest.fixture(scope="session")
def node_exe() -> str:
    found = shutil.which("node") or (
        r"C:\Program Files\nodejs\node.exe"
        if Path(r"C:\Program Files\nodejs\node.exe").is_file()
        else None
    )
    if not found:
        pytest.fail("Node.js executable not found for `node --check`")
    return found


def require_artifact(path: Path, description: str = "") -> Path:
    """Fail cleanly in acceptance mode, or skip only when KITE_E2E_ALLOW_MISSING=1."""
    if not path.exists():
        msg = f"Missing required KITE_OS artifact: {path}" + (
            f" ({description})" if description else ""
        )
        if os.environ.get("KITE_E2E_ALLOW_MISSING") == "1":
            pytest.skip(msg)
        pytest.fail(msg)
    return path


def run_ps1_syntax_check(ps_exe: str, script_path: Path) -> None:
    require_artifact(script_path, "PowerShell script")
    escaped = str(script_path.resolve()).replace("'", "''")
    ps_code = (
        f"$tokens = $null; $errors = $null; "
        f"[void][System.Management.Automation.Language.Parser]::ParseFile("
        f"'{escaped}', [ref]$tokens, [ref]$errors); "
        f"if ($errors -and $errors.Count -gt 0) {{ "
        f"  $errors | ForEach-Object {{ "
        f"    Write-Error ($_.Extent.StartLineNumber.ToString() + ':' + "
        f"$_.Extent.StartColumnNumber.ToString() + ' ' + $_.Message) "
        f"  }}; "
        f"  exit 1 "
        f"}}"
    )
    encoded = base64.b64encode(ps_code.encode("utf-16le")).decode("ascii")
    res = subprocess.run(
        [ps_exe, "-NoProfile", "-NonInteractive", "-EncodedCommand", encoded],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert res.returncode == 0, (
        f"PS 5.1 syntax error in {script_path}:\n{res.stderr}\n{res.stdout}"
    )


def run_sh_syntax_check(bash_exe: str, script_path: Path) -> None:
    require_artifact(script_path, "Bash script")
    res = subprocess.run(
        [bash_exe, "-n", str(script_path)],
        capture_output=True,
        text=True,
        timeout=20,
    )
    assert res.returncode == 0, f"Bash -n syntax error in {script_path}:\n{res.stderr}"


def run_js_syntax_check(node_path: str, js_path: Path) -> None:
    require_artifact(js_path, "JavaScript file")
    res = subprocess.run(
        [node_path, "--check", str(js_path)],
        capture_output=True,
        text=True,
        timeout=20,
    )
    assert res.returncode == 0, f"Node --check error in {js_path}:\n{res.stderr}"


def run_yaml_load_check(yaml_path: Path) -> Any:
    require_artifact(yaml_path, "YAML file")
    raw = yaml_path.read_text(encoding="utf-8")
    docs = list(yaml.safe_load_all(raw))
    assert docs and docs[0] is not None, f"Empty YAML document: {yaml_path}"
    return docs[0] if len(docs) == 1 else docs


def run_qml_structural_check(qml_path: Path) -> dict[str, Any]:
    """Structural Qt6/Quickshell QML validator (never invokes Qt 5.9.7 qmllint.exe)."""
    require_artifact(qml_path, "Qt6 QML file")
    raw_bytes = qml_path.read_bytes()
    assert not raw_bytes.startswith(b"\xef\xbb\xbf"), f"Unexpected UTF-8 BOM in {qml_path}"
    text = raw_bytes.decode("utf-8")

    stripped_chars: list[str] = []
    stack: list[tuple[str, int]] = []
    pairs = {"{": "}", "(": ")", "[": "]"}
    closing = {v: k for k, v in pairs.items()}
    i, n, line = 0, len(text), 1
    in_line_comment = False
    in_block_comment = False
    in_string: str | None = None

    while i < n:
        ch = text[i]
        nxt = text[i + 1] if i + 1 < n else ""
        if ch == "\n":
            line += 1
        if in_line_comment:
            if ch == "\n":
                in_line_comment = False
                stripped_chars.append("\n")
            i += 1
            continue
        if in_block_comment:
            if ch == "*" and nxt == "/":
                in_block_comment = False
                i += 2
            else:
                i += 1
            continue
        if in_string is not None:
            if ch == "\\":
                i += 2
                continue
            if ch == in_string:
                in_string = None
            elif ch == "\n" and in_string in ('"', "'"):
                raise AssertionError(
                    f"Unterminated string literal in {qml_path} near line {line}"
                )
            i += 1
            continue

        if ch == "/" and nxt == "/":
            in_line_comment = True
            i += 2
            continue
        if ch == "/" and nxt == "*":
            in_block_comment = True
            i += 2
            continue
        if ch in ('"', "'", "`"):
            in_string = ch
            stripped_chars.append(" ")
            i += 1
            continue

        if ch in pairs:
            stack.append((ch, line))
        elif ch in closing:
            assert stack and stack[-1][0] == closing[ch], (
                f"Unmatched '{ch}' in {qml_path} at line {line} (stack={stack[-3:]})"
            )
            stack.pop()
        stripped_chars.append(ch)
        i += 1

    assert not in_block_comment, f"Unterminated /* block comment in {qml_path}"
    assert in_string is None, f"Unterminated string literal at EOF in {qml_path}"
    assert not stack, f"Unclosed delimiters in {qml_path}: {stack}"

    stripped = "".join(stripped_chars)
    imports = re.findall(r"^\s*import\s+([^\r\n;]+)", stripped, flags=re.MULTILINE)
    assert imports, f"No QML import statements found in {qml_path}"
    for imp in imports:
        assert not re.match(r"^QtQuick\s+2\.", imp.strip()), (
            f"Legacy Qt5 import '{imp}' in {qml_path}"
        )
        assert "QtGraphicalEffects" not in imp or "Qt5Compat" in imp, (
            f"Legacy Qt5 QtGraphicalEffects in {qml_path}"
        )

    root_match = re.search(r"(?:^|\n)\s*([A-Z][A-Za-z0-9_.]*)\s*\{", stripped)
    assert root_match, f"No root QML ObjectType {{ ... }} declaration found in {qml_path}"
    return {"imports": imports, "root_type": root_match.group(1), "stripped": stripped}


@pytest.fixture(scope="session")
def ps1_syntax_check(powershell_exe: str) -> Callable[[Path], None]:
    return lambda p: run_ps1_syntax_check(powershell_exe, p)


@pytest.fixture(scope="session")
def sh_syntax_check(git_bash_exe: str) -> Callable[[Path], None]:
    return lambda p: run_sh_syntax_check(git_bash_exe, p)


@pytest.fixture(scope="session")
def js_syntax_check(node_exe: str) -> Callable[[Path], None]:
    return lambda p: run_js_syntax_check(node_exe, p)


@pytest.fixture(scope="session")
def yaml_load_check() -> Callable[[Path], Any]:
    return run_yaml_load_check


@pytest.fixture(scope="session")
def qml_structural_check() -> Callable[[Path], dict[str, Any]]:
    return run_qml_structural_check


# ---------------------------------------------------------------------------
# Hermetic environment & mock sysfs/proc builders
# ---------------------------------------------------------------------------


def build_hermetic_env(
    repo_root: Path,
    tmp_path: Path,
    extra_env: dict[str, str] | None = None,
) -> dict[str, str]:
    """Build isolated HOME / XDG_* / PYTHONPATH env so tests never touch host user dirs."""
    home_dir = tmp_path / "home"
    data_dir = tmp_path / "xdg_data"
    cfg_dir = tmp_path / "xdg_config"
    state_dir = tmp_path / "xdg_state"
    cache_dir = tmp_path / "xdg_cache"
    runtime_dir = tmp_path / "xdg_runtime"
    for d in (home_dir, data_dir, cfg_dir, state_dir, cache_dir, runtime_dir):
        d.mkdir(parents=True, exist_ok=True)

    python_paths = [
        str(repo_root / "kite-hw-tune"),
        str(repo_root / "kite-bridge"),
        str(repo_root / "kite-shell" / "settings"),
    ]
    existing_pp = os.environ.get("PYTHONPATH", "")
    if existing_pp:
        python_paths.append(existing_pp)

    env = os.environ.copy()
    env.update(
        {
            "HOME": str(home_dir),
            "USERPROFILE": str(home_dir),
            "XDG_DATA_HOME": str(data_dir),
            "XDG_CONFIG_HOME": str(cfg_dir),
            "XDG_STATE_HOME": str(state_dir),
            "XDG_CACHE_HOME": str(cache_dir),
            "XDG_RUNTIME_DIR": str(runtime_dir),
            "PYTHONPATH": os.pathsep.join(python_paths),
            "PYTHONUTF8": "1",
        }
    )
    env.pop("WAYLAND_DISPLAY", None)
    env.pop("DISPLAY", None)
    if extra_env:
        env.update(extra_env)
    return env


def create_mock_hw_roots(
    base_dir: Path,
    *,
    ram_mb: int | None = 8192,
    power_source: str | None = "AC",
    block_devices: dict[str, str | int | None] | None = None,
    include_power_supply: bool = True,
    meminfo_raw: str | None = None,
) -> tuple[Path, Path]:
    """Create mock /proc and /sys directory trees for kite-hw-tune hermetic runs."""
    proc_root = base_dir / "mock_proc"
    sys_root = base_dir / "mock_sys"
    proc_root.mkdir(parents=True, exist_ok=True)
    sys_root.mkdir(parents=True, exist_ok=True)

    if meminfo_raw is not None:
        (proc_root / "meminfo").write_text(meminfo_raw, encoding="utf-8")
    elif ram_mb is not None:
        kb = ram_mb * 1024
        (proc_root / "meminfo").write_text(
            f"MemTotal:       {kb} kB\nMemFree:        {kb // 2} kB\n",
            encoding="utf-8",
        )

    if include_power_supply and power_source is not None:
        ps_root = sys_root / "class" / "power_supply"
        ac_dir = ps_root / "AC"
        bat_dir = ps_root / "BAT0"
        ac_dir.mkdir(parents=True, exist_ok=True)
        bat_dir.mkdir(parents=True, exist_ok=True)
        (ac_dir / "type").write_text("Mains\n", encoding="utf-8")
        (bat_dir / "type").write_text("Battery\n", encoding="utf-8")
        if power_source.upper() == "AC":
            (ac_dir / "online").write_text("1\n", encoding="utf-8")
            (bat_dir / "status").write_text("Charging\n", encoding="utf-8")
        else:
            (ac_dir / "online").write_text("0\n", encoding="utf-8")
            (bat_dir / "status").write_text("Discharging\n", encoding="utf-8")

    block_root = sys_root / "block"
    block_root.mkdir(parents=True, exist_ok=True)
    if block_devices is not None:
        for dev, rot in block_devices.items():
            qdir = block_root / dev / "queue"
            qdir.mkdir(parents=True, exist_ok=True)
            if rot is not None:
                (qdir / "rotational").write_text(f"{rot}\n", encoding="utf-8")

    return proc_root, sys_root


def _extract_json_from_stdout(stdout: str) -> Any:
    text = stdout.strip()
    if not text:
        raise AssertionError("Expected JSON output on stdout, got empty output.")
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        idx = text.find("{")
        if idx != -1:
            return json.loads(text[idx:])
        idx_arr = text.find("[")
        if idx_arr != -1:
            return json.loads(text[idx_arr:])
        raise


def introspect_cli_help(
    repo_root: Path,
    python_exe: str,
    module_name: str,
    subcommand: str | None = None,
) -> dict[str, Any]:
    """Run `python -m <module> [subcommand] --help` and cache discovered flags."""
    cache_key = (module_name, subcommand or "")
    if cache_key in _CLI_HELP_CACHE:
        return _CLI_HELP_CACHE[cache_key]

    # Never write under repo_root; use system temp for --help probe
    import tempfile

    with tempfile.TemporaryDirectory() as td:
        env = build_hermetic_env(repo_root, Path(td))
        cmd = [python_exe, "-m", module_name]
        if subcommand:
            cmd.append(subcommand)
        cmd.append("--help")
        res = subprocess.run(cmd, env=env, capture_output=True, text=True, timeout=20)
        help_text = (res.stdout or "") + "\n" + (res.stderr or "")
        flags = set(re.findall(r"--[a-zA-Z0-9][a-zA-Z0-9_-]*", help_text))
        info = {"returncode": res.returncode, "text": help_text, "flags": flags}
        _CLI_HELP_CACHE[cache_key] = info
        return info


def _pick_flag(flags: set[str], candidates: tuple[str, ...]) -> str | None:
    for c in candidates:
        if c in flags:
            return c
    return None


def run_kite_hw_tune(
    repo_root: Path,
    python_exe: str,
    tmp_path: Path,
    *,
    ram_mb: int | None = 8192,
    power_source: str | None = "AC",
    block_devices: dict[str, str | int | None] | None = None,
    include_power_supply: bool = True,
    meminfo_raw: str | None = None,
    output_path: Path | None = None,
    extra_args: list[str] | None = None,
    pass_ram_flag: bool = True,
    pass_power_flag: bool = True,
) -> tuple[subprocess.CompletedProcess[str], dict[str, Any] | None]:
    """Invoke `python -m kite_hw_tune` hermetically via CLI --help discovery."""
    pkg_dir = require_artifact(repo_root / "kite-hw-tune" / "kite_hw_tune", "kite-hw-tune package")
    assert pkg_dir.is_dir()

    help_info = introspect_cli_help(repo_root, python_exe, "kite_hw_tune")
    flags: set[str] = help_info["flags"]

    hw_mock_dir = tmp_path / "hw_mock"
    proc_root, sys_root = create_mock_hw_roots(
        hw_mock_dir,
        ram_mb=ram_mb,
        power_source=power_source,
        block_devices=block_devices if block_devices is not None else {"sda": 0},
        include_power_supply=include_power_supply,
        meminfo_raw=meminfo_raw,
    )
    out_file = output_path or (tmp_path / "hw-profile.json")

    cmd = [python_exe, "-m", "kite_hw_tune"]
    proc_flag = _pick_flag(flags, ("--proc-root", "--proc", "--procfs"))
    if proc_flag:
        cmd.extend([proc_flag, str(proc_root)])

    sys_flag = _pick_flag(flags, ("--sys-root", "--sysfs-root", "--sysfs", "--sys"))
    if sys_flag:
        cmd.extend([sys_flag, str(sys_root)])

    if pass_ram_flag and ram_mb is not None:
        ram_flag = _pick_flag(flags, ("--ram-mb", "--ram"))
        if ram_flag:
            cmd.extend([ram_flag, str(ram_mb)])

    if pass_power_flag and power_source is not None:
        pwr_flag = _pick_flag(flags, ("--power", "--power-source"))
        if pwr_flag:
            cmd.extend([pwr_flag, power_source])

    out_flag = _pick_flag(flags, ("--output-profile", "--output", "--out", "--profile-out"))
    if out_flag:
        cmd.extend([out_flag, str(out_file)])

    if "--dry-run" in flags:
        cmd.append("--dry-run")
    if "--json" in flags:
        cmd.append("--json")
    if extra_args:
        cmd.extend(extra_args)

    env = build_hermetic_env(
        repo_root,
        tmp_path,
        extra_env={
            "KITE_PROC_ROOT": str(proc_root),
            "KITE_SYS_ROOT": str(sys_root),
            "KITE_HW_PROFILE_PATH": str(out_file),
            "KITE_HW_TUNE_OUTPUT_PROFILE": str(out_file),
            "KITE_DRY_RUN": "1",
        },
    )
    res = subprocess.run(cmd, env=env, capture_output=True, text=True, timeout=30)
    parsed: dict[str, Any] | None = None
    if res.returncode == 0:
        if out_file.is_file():
            parsed = json.loads(out_file.read_text(encoding="utf-8"))
        elif res.stdout.strip():
            parsed = _extract_json_from_stdout(res.stdout)
    return res, parsed


def run_kite_bridge(
    repo_root: Path,
    python_exe: str,
    tmp_path: Path,
    args: list[str],
    *,
    hw_profile_path: Path | None = None,
    kvm_available: bool = True,
    ntsync_available: bool = True,
    binder_available: bool = True,
    extra_env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    """Invoke `python -m kite_bridge` hermetically without touching user home."""
    pkg_dir = require_artifact(repo_root / "kite-bridge" / "kite_bridge", "kite-bridge package")
    assert pkg_dir.is_dir()

    dev_root = tmp_path / "mock_dev"
    dev_root.mkdir(parents=True, exist_ok=True)
    if kvm_available:
        (dev_root / "kvm").write_text("", encoding="utf-8")
    if ntsync_available:
        (dev_root / "ntsync").write_text("", encoding="utf-8")
    if binder_available:
        (dev_root / "binder").write_text("", encoding="utf-8")

    env_map: dict[str, str] = {
        "KITE_DEV_ROOT": str(dev_root),
        "KITE_DEV_KVM": "1" if kvm_available else "0",
        "KITE_DEV_NTSYNC": "1" if ntsync_available else "0",
        "KITE_DEV_BINDER": "1" if binder_available else "0",
    }
    if hw_profile_path is not None:
        env_map["KITE_HW_PROFILE_PATH"] = str(hw_profile_path)
    if extra_env:
        env_map.update(extra_env)

    env = build_hermetic_env(repo_root, tmp_path, extra_env=env_map)
    subcmd = args[0] if args and not args[0].startswith("-") else None
    help_info = introspect_cli_help(repo_root, python_exe, "kite_bridge", subcmd)
    final_args = list(args)
    if hw_profile_path is not None:
        prof_flag = _pick_flag(help_info["flags"], ("--hw-profile", "--profile"))
        if prof_flag and prof_flag not in final_args:
            final_args.extend([prof_flag, str(hw_profile_path)])

    cmd = [python_exe, "-m", "kite_bridge", *final_args]
    return subprocess.run(cmd, env=env, capture_output=True, text=True, timeout=30)


def resolve_kite_settings_module(repo_root: Path, python_exe: str) -> str:
    """Discover whether kite_settings CLI is exposed as `kite_settings` or `kite_settings.cli`."""
    pkg_dir = require_artifact(
        repo_root / "kite-shell" / "settings" / "kite_settings",
        "kite_settings package",
    )
    if (pkg_dir / "__main__.py").is_file():
        return "kite_settings"
    if (pkg_dir / "cli.py").is_file():
        return "kite_settings.cli"
    info = introspect_cli_help(repo_root, python_exe, "kite_settings")
    if info["returncode"] == 0:
        return "kite_settings"
    return "kite_settings.cli"


def run_kite_settings(
    repo_root: Path,
    python_exe: str,
    tmp_path: Path,
    args: list[str] | None = None,
    *,
    hw_profile_path: Path | None = None,
    extra_env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    """Invoke `python -m kite_settings[.cli]` hermetically."""
    pkg_dir = require_artifact(
        repo_root / "kite-shell" / "settings" / "kite_settings",
        "kite_settings package",
    )
    assert pkg_dir.is_dir()

    module_name = resolve_kite_settings_module(repo_root, python_exe)
    env_map: dict[str, str] = {}
    if hw_profile_path is not None:
        env_map["KITE_HW_PROFILE_PATH"] = str(hw_profile_path)
    if extra_env:
        env_map.update(extra_env)

    env = build_hermetic_env(repo_root, tmp_path, extra_env=env_map)
    cmd = [python_exe, "-m", module_name, *(args or [])]
    return subprocess.run(cmd, env=env, capture_output=True, text=True, timeout=30)


def write_minimal_apk(dest: Path) -> Path:
    """Write a minimal valid ZIP-based .apk archive containing AndroidManifest.xml."""
    import zipfile

    dest.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(dest, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("AndroidManifest.xml", b"KITE_DUMMY_MANIFEST")
        zf.writestr("classes.dex", b"dex\n035\x00")
    return dest


def write_minimal_aab(dest: Path) -> Path:
    """Write a minimal valid ZIP-based .aab archive containing BundleConfig.pb and manifest."""
    import zipfile

    dest.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(dest, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("BundleConfig.pb", b"KITE_BUNDLE_CFG")
        zf.writestr("base/manifest/AndroidManifest.xml", b"KITE_DUMMY_MANIFEST")
    return dest


def invoke_kite_settings_cli(
    repo_root: Path,
    python_exe: str,
    tmp_path: Path,
    *,
    preset: str | None = None,
    settings_dict: dict[str, Any] | None = None,
    hw_profile_path: Path | None = None,
) -> tuple[subprocess.CompletedProcess[str], dict[str, Any] | None, str]:
    """Invoke kite_settings CLI via `--help` discovery to apply/sync settings and Hyprland conf."""
    module_name = resolve_kite_settings_module(repo_root, python_exe)
    help_info = introspect_cli_help(repo_root, python_exe, module_name)
    flags: set[str] = help_info["flags"]
    help_text: str = help_info["text"]

    cfg_dir = tmp_path / "xdg_config"
    settings_out = cfg_dir / "kite-os" / "settings.json"
    hypr_out = cfg_dir / "hypr" / "kite-glass-runtime.conf"
    settings_out.parent.mkdir(parents=True, exist_ok=True)
    hypr_out.parent.mkdir(parents=True, exist_ok=True)

    if settings_dict is not None:
        settings_out.write_text(json.dumps(settings_dict, indent=2), encoding="utf-8")

    args: list[str] = []
    if preset is not None and re.search(r"\bpreset\b", help_text) and "--preset" not in flags:
        args.extend(["preset", preset])
    else:
        for sub in ("sync", "apply", "generate", "render"):
            if re.search(rf"\b{sub}\b", help_text):
                args.append(sub)
                break
        if preset is not None and "--preset" in flags:
            args.extend(["--preset", preset])

    sub_help = (
        introspect_cli_help(repo_root, python_exe, module_name, args[0])
        if args and not args[0].startswith("-")
        else help_info
    )
    all_flags = flags | sub_help["flags"]

    if "--settings" in all_flags:
        args.extend(["--settings", str(settings_out)])
    if hw_profile_path is not None and "--hw-profile" in all_flags:
        args.extend(["--hw-profile", str(hw_profile_path)])
    if "--hypr-conf" in all_flags:
        args.extend(["--hypr-conf", str(hypr_out)])
    elif "--runtime-conf" in all_flags:
        args.extend(["--runtime-conf", str(hypr_out)])
    if "--no-reload" in all_flags:
        args.append("--no-reload")
    if "--json" in all_flags:
        args.append("--json")

    res = run_kite_settings(
        repo_root,
        python_exe,
        tmp_path,
        args=args,
        hw_profile_path=hw_profile_path,
        extra_env={
            "KITE_SETTINGS_PATH": str(settings_out),
            "KITE_HYPR_GLASS_CONF": str(hypr_out),
            "KITE_HYPR_RUNTIME_CONF": str(hypr_out),
            **({"KITE_THEME_PRESET": preset} if preset else {}),
        },
    )

    alt_settings = tmp_path / "home" / ".config" / "kite-os" / "settings.json"
    alt_hypr = tmp_path / "home" / ".config" / "hypr" / "kite-glass-runtime.conf"
    s_file = settings_out if settings_out.is_file() else alt_settings
    h_file = hypr_out if hypr_out.is_file() else alt_hypr

    loaded_settings: dict[str, Any] | None = None
    if s_file.is_file():
        loaded_settings = json.loads(s_file.read_text(encoding="utf-8"))
    elif res.returncode == 0 and res.stdout.strip():
        parsed = _extract_json_from_stdout(res.stdout)
        loaded_settings = parsed.get("settings", parsed) if isinstance(parsed, dict) else None

    hypr_text = h_file.read_text(encoding="utf-8") if h_file.is_file() else ""
    return res, loaded_settings, hypr_text


def build_kite_bridge_lifecycle_args(
    repo_root: Path,
    python_exe: str,
    subsystem: str = "all",
    action: str = "status",
    *,
    idle_seconds: int | None = None,
    dry_run: bool = True,
    as_json: bool = True,
) -> list[str]:
    """Build `kite_bridge lifecycle` CLI arguments via `--help` discovery."""
    help_info = introspect_cli_help(repo_root, python_exe, "kite_bridge", "lifecycle")
    help_txt = help_info["text"]
    flags: set[str] = help_info["flags"]
    args = ["lifecycle"]
    if (subsystem in help_txt or "subsystem" in help_txt) and (action in help_txt or "action" in help_txt):
        args.extend([subsystem, action])
    if idle_seconds is not None:
        idle_flag = _pick_flag(flags, ("--idle-seconds", "--idle-sec"))
        if idle_flag:
            args.extend([idle_flag, str(idle_seconds)])
    if dry_run and "--dry-run" in flags:
        args.append("--dry-run")
    if as_json and "--json" in flags:
        args.append("--json")
    return args


def validate_hw_profile_v1(profile: dict[str, Any]) -> None:
    jsonschema.validate(instance=profile, schema=HW_PROFILE_SCHEMA_V1)


def validate_settings_v1(settings: dict[str, Any]) -> None:
    jsonschema.validate(instance=settings, schema=SETTINGS_SCHEMA_V1)


def validate_bridge_inspect_json(payload: dict[str, Any]) -> None:
    jsonschema.validate(instance=payload, schema=BRIDGE_INSPECT_SCHEMA)


def is_prohibitory_line(line: str) -> bool:
    low = line.lower()
    return any(marker in low for marker in PROHIBITORY_MARKERS)


def scan_active_forbidden_assignments(root: Path, rel_dirs: list[str]) -> list[str]:
    """Scan active config/code lines across target dirs for forbidden drivers.

    Ignores comments (#, //), prohibitory doc lines, and test directories.
    """
    forbidden_iris = "MESA_LOADER_DRIVER_OVERRIDE" + "=" + "iris"
    forbidden_ihd = "LIBVA_DRIVER_NAME" + "=" + "iHD"
    forbidden_pkg = "intel-media-" + "driver"
    forbidden_dxvk = "DXVK_VER" + "=2."

    violations: list[str] = []
    for rel in rel_dirs:
        base = root / rel
        if not base.exists():
            continue
        for fpath in base.rglob("*"):
            if not fpath.is_file():
                continue
            if "tests" in fpath.parts or "__pycache__" in fpath.parts:
                continue
            if fpath.suffix.lower() in {".png", ".jpg", ".ico", ".svg", ".woff2", ".pyc"}:
                continue
            try:
                content = fpath.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            for idx, raw_line in enumerate(content.splitlines(), start=1):
                s = raw_line.strip()
                if not s or s.startswith("#") or s.startswith("//"):
                    continue
                if is_prohibitory_line(s):
                    continue
                if (
                    forbidden_iris in s
                    or re.search(r"MESA_LOADER_DRIVER_OVERRIDE\s*=\s*['\"]?iris\b", s)
                    or re.search(r"\benv\s*=.*MESA_LOADER_DRIVER_OVERRIDE,\s*iris\b", s)
                ):
                    violations.append(f"{fpath}:{idx}: active iris override -> {s}")
                if (
                    forbidden_ihd in s
                    or re.search(r"LIBVA_DRIVER_NAME\s*=\s*['\"]?iHD\b", s)
                    or re.search(r"\benv\s*=.*LIBVA_DRIVER_NAME,\s*iHD\b", s)
                ):
                    violations.append(f"{fpath}:{idx}: active iHD override -> {s}")
                if forbidden_pkg in s and not s.startswith(("assert", "if ", "print(", "echo ", "\"", "'")):
                    # Allow explicit rejection/check code in validators
                    if "reject" not in s.lower() and "forbidden" not in s.lower() and "not in" not in s.lower() and "grep" not in s.lower():
                        violations.append(f"{fpath}:{idx}: active {forbidden_pkg} -> {s}")
                if re.search(r"DXVK_VER\s*=\s*['\"]?2\.", s):
                    violations.append(f"{fpath}:{idx}: active {forbidden_dxvk} -> {s}")
    return violations


# ---------------------------------------------------------------------------
# Ephemeral static HTTP server & Playwright Chromium fixtures
# ---------------------------------------------------------------------------


class _QuietPreviewHandler(http.server.SimpleHTTPRequestHandler):
    extensions_map = {
        **http.server.SimpleHTTPRequestHandler.extensions_map,
        ".js": "text/javascript; charset=utf-8",
        ".mjs": "text/javascript; charset=utf-8",
        ".css": "text/css; charset=utf-8",
        ".html": "text/html; charset=utf-8",
        ".json": "application/json; charset=utf-8",
        ".svg": "image/svg+xml",
    }

    def log_message(self, format: str, *args: Any) -> None:
        pass


class _ThreadedHTTPServer(socketserver.ThreadingMixIn, http.server.HTTPServer):
    daemon_threads = True


@pytest.fixture(scope="module")
def preview_server_url(repo_root: Path):
    preview_dir = require_artifact(repo_root / "kite-shell" / "preview", "preview directory")
    require_artifact(preview_dir / "index.html", "preview index.html")
    handler = functools.partial(_QuietPreviewHandler, directory=str(preview_dir))
    server = _ThreadedHTTPServer(("127.0.0.1", 0), handler)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{port}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


@pytest.fixture(scope="session")
def playwright_browser():
    from playwright.sync_api import sync_playwright

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        try:
            yield browser
        finally:
            browser.close()


@pytest.fixture
def playwright_page(playwright_browser):
    context = playwright_browser.new_context(viewport={"width": 1366, "height": 768})
    page = context.new_page()
    console_errors: list[str] = []
    page_errors: list[str] = []
    http_errors: list[str] = []
    failed_requests: list[str] = []

    page.on(
        "console",
        lambda msg: console_errors.append(msg.text) if msg.type == "error" else None,
    )
    page.on("pageerror", lambda err: page_errors.append(str(err)))
    page.on(
        "response",
        lambda resp: http_errors.append(f"{resp.status} {resp.url}")
        if resp.status >= 400
        else None,
    )
    page.on(
        "requestfailed",
        lambda req: failed_requests.append(f"{req.url}: {req.failure}"),
    )

    page._kite_errors = {  # type: ignore[attr-defined]
        "console": console_errors,
        "page": page_errors,
        "http": http_errors,
        "failed": failed_requests,
    }
    try:
        yield page
    finally:
        context.close()
