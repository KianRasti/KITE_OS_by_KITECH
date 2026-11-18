from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

from scripts.tests.m1_helpers import BASH_EXE, POWERSHELL_EXE, REPO_ROOT

PS7_ONLY_PATTERNS = [
    (re.compile(r"\?\?=?"), "null-coalescing operator (?? / ??=) is PS 7+ only"),
    (re.compile(r"(?m)^[^#\r\n]*?(?<![&])&&(?![&])"), "pipeline chain && is PS 7+ only"),
    (re.compile(r"(?m)^[^#\r\n]*?(?<![|])\|\|(?![|])"), "pipeline chain || is PS 7+ only"),
    (re.compile(r"ForEach-Object\s+-Parallel\b", re.IGNORECASE), "-Parallel is PS 7+ only"),
]


def _m1_ps1_files() -> list[Path]:
    return sorted((REPO_ROOT / "scripts").glob("*.ps1"))


def _m1_sh_files() -> list[Path]:
    files: list[Path] = []
    for base in (REPO_ROOT / "scripts", REPO_ROOT / "iso-profile"):
        if base.is_dir():
            files.extend(sorted(base.rglob("*.sh")))
    hook = REPO_ROOT / "iso-profile" / "airootfs" / "usr" / "local" / "bin" / "kite-postinstall-hook"
    if hook.is_file():
        files.append(hook)
    return files


def _strip_ps1_quotes_and_comments(text: str) -> str:
    """Strip PowerShell comments and string literals so only PS operators/tokens remain."""
    text = re.sub(r"<#.*?#>", "", text, flags=re.DOTALL)
    text = re.sub(r"'([^']|'')*'", "''", text)
    text = re.sub(r'"([^"`]|`.)*"', '""', text)
    return "\n".join(ln.split("#", 1)[0] for ln in text.splitlines())


@pytest.mark.parametrize("ps1_path", _m1_ps1_files(), ids=lambda p: p.name)
def test_powershell_51_syntax(ps1_path: Path) -> None:
    text = ps1_path.read_text(encoding="utf-8")
    stripped = _strip_ps1_quotes_and_comments(text)
    for pattern, reason in PS7_ONLY_PATTERNS:
        assert not pattern.search(stripped), f"{ps1_path.name}: {reason}"

    if sys.platform == "win32":
        env = os.environ.copy()
        env["TARGET_PS1"] = str(ps1_path)
        cmd = [
            POWERSHELL_EXE,
            "-NoProfile",
            "-Command",
            (
                "$t=$null; $e=$null; "
                "$null=[System.Management.Automation.Language.Parser]::ParseFile($env:TARGET_PS1,[ref]$t,[ref]$e); "
                "if ($e.Count -gt 0) { $e | ForEach-Object { Write-Error $_.Message }; exit 1 }"
            ),
        ]
        res = subprocess.run(cmd, env=env, capture_output=True, text=True, check=False)
        assert res.returncode == 0, f"PS 5.1 parse error in {ps1_path.name}: {res.stderr}\n{res.stdout}"


@pytest.mark.parametrize("sh_path", _m1_sh_files(), ids=lambda p: p.relative_to(REPO_ROOT).as_posix())
def test_bash_syntax_and_lf(sh_path: Path) -> None:
    raw = sh_path.read_bytes()
    assert b"\r\n" not in raw, f"{sh_path} must use LF line endings"
    assert not raw.startswith(b"\xef\xbb\xbf"), f"{sh_path} must not have UTF-8 BOM"
    if sys.platform == "win32":
        assert Path(BASH_EXE).is_file(), f"Git Bash not found at {BASH_EXE}"
    res = subprocess.run([BASH_EXE, "-n", str(sh_path)], capture_output=True, text=True, check=False)
    assert res.returncode == 0, f"bash -n failed for {sh_path}: {res.stderr}"
