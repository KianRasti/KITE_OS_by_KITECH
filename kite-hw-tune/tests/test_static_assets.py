"""Static validation tests for systemd units, udev rules, configs, and install.sh."""

from __future__ import annotations

import configparser
import os
import re
import shutil
import subprocess
import sys
import tomllib
import xml.etree.ElementTree as ET
from pathlib import Path

from tests.conftest import PACKAGE_ROOT

GIT_BASH = Path(r"C:\Program Files\Git\bin\bash.exe")
UDEV_TOKEN_RE = re.compile(
    r'^(?:[A-Z_]+(?:\{[^}]+\})?)(?:==|!=|=|\+=|:=)"[^"]*"$'
)


def _split_udev_tokens(line: str) -> list[str]:
    tokens: list[str] = []
    current: list[str] = []
    in_quotes = False
    for ch in line:
        if ch == '"':
            in_quotes = not in_quotes
            current.append(ch)
        elif ch == "," and not in_quotes:
            tok = "".join(current).strip()
            if tok:
                tokens.append(tok)
            current = []
        else:
            current.append(ch)
    tail = "".join(current).strip()
    if tail:
        tokens.append(tail)
    return tokens


def test_all_files_utf8_no_bom_and_lf_only() -> None:
    suffixes = {".py", ".toml", ".sh", ".service", ".rules", ".conf", ".xml"}
    checked = 0
    for path in sorted(PACKAGE_ROOT.rglob("*")):
        if not path.is_file() or path.suffix not in suffixes:
            continue
        if "__pycache__" in path.parts:
            continue
        raw = path.read_bytes()
        assert not raw.startswith(b"\xef\xbb\xbf"), f"UTF-8 BOM found in {path}"
        assert b"\r\n" not in raw, f"CRLF line endings found in {path}"
        raw.decode("utf-8")
        checked += 1
    assert checked >= 15


def test_pyproject_toml_valid() -> None:
    pyproject_path = PACKAGE_ROOT / "pyproject.toml"
    data = tomllib.loads(pyproject_path.read_text(encoding="utf-8"))
    scripts = data["project"]["scripts"]
    assert scripts["kite-hw-tune"] == "kite_hw_tune.cli:main_hw_tune"
    assert scripts["kite-power"] == "kite_hw_tune.cli:main_power"
    assert data["project"]["dependencies"] == []


def test_install_sh_syntax_and_assets() -> None:
    install_sh = PACKAGE_ROOT / "install.sh"
    assert install_sh.exists()
    text = install_sh.read_text(encoding="utf-8")
    assert text.startswith("#!/usr/bin/env bash\n")
    assert "set -euo pipefail" in text
    for expected_ref in (
        "systemd/kite-hw-tune.service",
        "systemd/kite-power.service",
        "udev/99-kite-power.rules",
        "udev/99-kite-storage.rules",
        "config/10-kite-haswell.conf",
        "config/modprobe-kite-haswell.conf",
        "config/99-kite-base.conf",
        "config/thermal-conf.xml",
    ):
        assert expected_ref in text

    bash_exe = str(GIT_BASH) if GIT_BASH.exists() else shutil.which("bash")
    assert bash_exe is not None, "Bash binary required for install.sh syntax check"
    proc = subprocess.run(
        [bash_exe, "-n", str(install_sh)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr


def test_install_sh_destdir_staging(tmp_path: Path) -> None:
    install_sh = PACKAGE_ROOT / "install.sh"
    bash_exe = str(GIT_BASH) if GIT_BASH.exists() else shutil.which("bash")
    assert bash_exe is not None, "Bash binary required for install.sh staging test"

    stage = tmp_path / "stage"
    env = dict(os.environ)
    env["PYTHON_BIN"] = Path(sys.executable).as_posix()

    proc = subprocess.run(
        [bash_exe, str(install_sh), "--destdir", str(stage), "--no-enable"],
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )
    assert proc.returncode == 0, f"STDOUT:\n{proc.stdout}\nSTDERR:\n{proc.stderr}"

    expected_files = [
        stage / "usr" / "local" / "bin" / "kite-hw-tune",
        stage / "usr" / "local" / "bin" / "kite-power",
        stage / "etc" / "systemd" / "system" / "kite-hw-tune.service",
        stage / "etc" / "systemd" / "system" / "kite-power.service",
        stage / "etc" / "udev" / "rules.d" / "99-kite-power.rules",
        stage / "etc" / "udev" / "rules.d" / "99-kite-storage.rules",
        stage / "etc" / "environment.d" / "10-kite-haswell.conf",
        stage / "etc" / "modprobe.d" / "kite-haswell.conf",
        stage / "etc" / "sysctl.d" / "99-kite-base.conf",
        stage / "etc" / "thermald" / "thermal-conf.xml",
    ]
    for expected in expected_files:
        assert expected.is_file(), f"Missing staged file: {expected}"

    staged_init = list(stage.rglob("kite_hw_tune/__init__.py"))
    assert staged_init, f"Missing staged kite_hw_tune package under {stage}"


def test_systemd_units_valid() -> None:
    hw_unit = PACKAGE_ROOT / "systemd" / "kite-hw-tune.service"
    power_unit = PACKAGE_ROOT / "systemd" / "kite-power.service"

    for unit_path in (hw_unit, power_unit):
        raw = unit_path.read_text(encoding="utf-8")
        assert "\\" not in raw
        cp = configparser.ConfigParser(interpolation=None)
        cp.read_string(raw)
        assert cp.has_section("Unit")
        assert cp.has_section("Service")
        assert cp.has_section("Install")
        assert cp.get("Service", "Type") == "oneshot"
        assert cp.get("Service", "ExecStart").startswith("/usr/local/bin/")

    cp_hw = configparser.ConfigParser(interpolation=None)
    cp_hw.read_string(hw_unit.read_text(encoding="utf-8"))
    assert cp_hw.get("Service", "RemainAfterExit") == "yes"

    cp_power = configparser.ConfigParser(interpolation=None)
    cp_power.read_string(power_unit.read_text(encoding="utf-8"))
    assert not cp_power.has_option("Service", "RemainAfterExit")


def test_udev_rules_valid() -> None:
    power_rules = PACKAGE_ROOT / "udev" / "99-kite-power.rules"
    storage_rules = PACKAGE_ROOT / "udev" / "99-kite-storage.rules"

    for rules_path in (power_rules, storage_rules):
        lines = rules_path.read_text(encoding="utf-8").splitlines()
        rule_lines = [ln.strip() for ln in lines if ln.strip() and not ln.strip().startswith("#")]
        assert rule_lines
        for line in rule_lines:
            tokens = _split_udev_tokens(line)
            assert tokens
            for tok in tokens:
                assert UDEV_TOKEN_RE.match(tok), f"Malformed udev token {tok!r} in {rules_path}"

    power_text = power_rules.read_text(encoding="utf-8")
    assert 'SUBSYSTEM=="power_supply"' in power_text
    assert 'ENV{SYSTEMD_WANTS}="kite-power.service"' in power_text

    storage_text = storage_rules.read_text(encoding="utf-8")
    assert 'SUBSYSTEM=="block"' in storage_text
    assert "kyber" in storage_text
    assert "bfq" in storage_text


def test_hardware_configs_and_thermal_xml() -> None:
    env_conf = (PACKAGE_ROOT / "config" / "10-kite-haswell.conf").read_text(encoding="utf-8")
    assert "MESA_LOADER_DRIVER_OVERRIDE=crocus" in env_conf
    assert "LIBVA_DRIVER_NAME=i965" in env_conf

    modprobe_conf = (PACKAGE_ROOT / "config" / "modprobe-kite-haswell.conf").read_text(
        encoding="utf-8"
    )
    assert "enable_fbc=1" in modprobe_conf
    assert "fastboot=1" in modprobe_conf
    assert "snd_hda_intel" in modprobe_conf
    assert "iwlwifi" in modprobe_conf
    assert "intel_pstate=active" in modprobe_conf

    base_sysctl = (PACKAGE_ROOT / "config" / "99-kite-base.conf").read_text(encoding="utf-8")
    assert "intel_pstate=active" in base_sysctl

    thermal_xml = PACKAGE_ROOT / "config" / "thermal-conf.xml"
    tree = ET.parse(thermal_xml)
    root = tree.getroot()
    assert root.tag == "ThermalConfiguration"
    assert root.findtext(".//ProductName") == "HP EliteBook Folio 9480m"
