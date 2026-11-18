"""Hardware invariant and cross-platform path hygiene checks for kite-hw-tune."""

from __future__ import annotations

import json
import re
from pathlib import Path

from tests.conftest import MockSysfsBuilder, PACKAGE_ROOT, make_tuner

# Constructed dynamically so this test file itself never triggers naive string scans.
FORBIDDEN_DRIVER_TOKENS = (
    "ir" + "is",
    "iH" + "D",
    "intel-media-" + "driver",
    "DXVK " + "2.",
    "dxvk-" + "2.",
)

FORBIDDEN_WORD_PATTERNS = tuple(
    re.compile(rf"\b{re.escape(tok)}", re.IGNORECASE)
    for tok in FORBIDDEN_DRIVER_TOKENS
)


def _iter_production_files() -> list[Path]:
    files: list[Path] = []
    for sub in ("kite_hw_tune", "systemd", "udev", "config"):
        base = PACKAGE_ROOT / sub
        if base.exists():
            for path in sorted(base.rglob("*")):
                if path.is_file() and "__pycache__" not in path.parts:
                    files.append(path)
    for root_file in ("install.sh", "pyproject.toml"):
        candidate = PACKAGE_ROOT / root_file
        if candidate.exists():
            files.append(candidate)
    return files


def test_zero_forbidden_driver_tokens_in_production_files() -> None:
    prod_files = _iter_production_files()
    assert len(prod_files) >= 12
    for path in prod_files:
        text = path.read_text(encoding="utf-8")
        for pattern in FORBIDDEN_WORD_PATTERNS:
            assert not pattern.search(text), (
                f"Forbidden driver reference matched {pattern.pattern!r} in {path}"
            )


def test_positive_hardware_invariants_and_posix_hygiene(tmp_path: Path) -> None:
    builder = MockSysfsBuilder(tmp_path)
    builder.set_meminfo_kb(8192 * 1024)
    builder.add_block_device("sda", rotational="0", scheduler="[mq-deadline] kyber\n")
    builder.set_power_supply(mains_online="1")

    tuner = make_tuner(builder)
    res = tuner.run_hw_tune(apply_system=True, write_files=True, write_env_file=True)

    profile = res.profile.to_dict()
    assert profile["subsystems"]["wine"]["dxvk_version"] == "1.10.3"
    assert profile["subsystems"]["wine"]["ntsync"] is True
    assert profile["blur"]["size"] <= 6
    assert profile["blur"]["passes"] <= 2

    serialized = json.dumps(profile, indent=2)
    assert "\\" not in serialized
    assert "C:" not in serialized

    env_text = (builder.etc_dir / "environment.d" / "10-kite-haswell.conf").read_text(
        encoding="utf-8"
    )
    assert "MESA_LOADER_DRIVER_OVERRIDE=crocus" in env_text
    assert "LIBVA_DRIVER_NAME=i965" in env_text
    for pattern in FORBIDDEN_WORD_PATTERNS:
        assert not pattern.search(serialized)
        assert not pattern.search(env_text)
