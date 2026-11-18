#!/usr/bin/env python3
"""KITE_OS (HP EliteBook Folio 9480m) syntax-aware repository invariant checker."""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any

try:
    import yaml  # type: ignore
except ImportError:  # pragma: no cover
    yaml = None

EXPECTED_AGENTS_SHA256 = "2c9c5fc4dc8353e4ba91c7c99c798b7db4603f6cefc882295dc5e966a3169de5"
EXPECTED_LEGACY_AGENTS_SHA256 = "c573df40a641d742d9b04ed3fa27ecb6c2a3e81400a2f7145cdfc9d79f06191b"
EXPECTED_SKILL_SHA256 = "639c61b21082ebca9dcd44c95bcf075876a1ec654f94b24ed7a2168e8056ba8b"

EXCLUDED_DIRS = {
    ".git",
    ".agents",
    "out",
    "work",
    "node_modules",
    "__pycache__",
    ".pytest_cache",
    ".venv",
    "tests",
}

M1_MODULES = ("iso-profile", "scripts", ".github")
ALL_MODULES = (
    "iso-profile",
    "scripts",
    ".github",
    "kite-hw-tune",
    "kite-shell",
    "kite-bridge",
    "kite-ai",
    "installer",
)

FORBIDDEN_PKG_RE = re.compile(
    r"^(?:intel-media-driver|libva-intel-media-driver|mesa-iris|iris|vkd3d|vkd3d-proton(?:-bin)?|"
    r"dxvk(?:-bin|-mingw-git)?(?:>=|>|==|=)?2(?:\..*)?)$",
    re.IGNORECASE,
)

FORBIDDEN_ARTIFACT_RE = re.compile(
    r"(?:intel-media-driver|iHD_drv_video|iris_dri|vkd3d-proton|dxvk[-_/]?v?2\.[0-9]+|dxvk20\d\d)",
    re.IGNORECASE,
)

DXVK_2X_VAL_RE = re.compile(r"^\s*(?:>=|>|==|=)?\s*v?2(?:\.|$)", re.IGNORECASE)
DESCRIPTIVE_YAML_KEYS = {"name", "description", "label", "title", "summary", "comment", "notes"}


def _rel(path: Path, root: Path) -> str:
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return path.as_posix()


def _is_excluded_from_negative_scan(path: Path, root: Path) -> bool:
    rel = _rel(path, root)
    parts = rel.split("/")
    for part in parts[:-1]:
        if part in EXCLUDED_DIRS:
            return True
    name = path.name
    if path.suffix.lower() == ".md":
        return True
    if name.startswith("test_") and path.suffix.lower() == ".py":
        return True
    if name.endswith("_test.py"):
        return True
    if rel == "scripts/check_invariants.py":
        return True
    return False


def _strip_ini_comments(text: str) -> list[tuple[int, str]]:
    """Strip # comments outside quotes from INI/env/conf lines, returning (lineno, line)."""
    out: list[tuple[int, str]] = []
    for idx, raw_line in enumerate(text.splitlines(), start=1):
        in_single = False
        in_double = False
        escaped = False
        chars: list[str] = []
        for ch in raw_line:
            if escaped:
                chars.append(ch)
                escaped = False
                continue
            if ch == "\\" and in_double:
                chars.append(ch)
                escaped = True
                continue
            if ch == "'" and not in_double:
                in_single = not in_single
                chars.append(ch)
            elif ch == '"' and not in_single:
                in_double = not in_double
                chars.append(ch)
            elif ch == "#" and not in_single and not in_double:
                break
            else:
                chars.append(ch)
        cleaned = "".join(chars).strip()
        if cleaned:
            out.append((idx, cleaned))
    return out


def _strip_shell_comments(text: str) -> str:
    """Deterministic char-by-char comment stripper for Bash scripts (preserves heredocs and quotes)."""
    n = len(text)
    i = 0
    out: list[str] = []
    in_single = False
    in_double = False
    escaped = False
    heredoc_delim: str | None = None

    while i < n:
        ch = text[i]
        if heredoc_delim is not None:
            line_end = text.find("\n", i)
            if line_end == -1:
                line = text[i:]
                out.append(line)
                break
            line = text[i:line_end]
            out.append(line + "\n")
            if line.lstrip("\t") == heredoc_delim or line == heredoc_delim:
                heredoc_delim = None
            i = line_end + 1
            continue

        if escaped:
            out.append(ch)
            escaped = False
            i += 1
            continue

        if ch == "\\" and not in_single:
            out.append(ch)
            escaped = True
            i += 1
            continue

        if ch == "'" and not in_double:
            in_single = not in_single
            out.append(ch)
            i += 1
            continue

        if ch == '"' and not in_single:
            in_double = not in_double
            out.append(ch)
            i += 1
            continue

        if not in_single and not in_double:
            if ch == "<" and i + 1 < n and text[i + 1] == "<":
                # Check for heredoc (<<EOF, <<-EOF, <<'EOF', <<"EOF") not <<<
                if i + 2 < n and text[i + 2] != "<":
                    m = re.match(r"<<-?\s*(['\"]?)([A-Za-z_][A-Za-z0-9_]*)\1", text[i:])
                    if m:
                        heredoc_delim_pending = m.group(2)
                        rest_of_line_end = text.find("\n", i)
                        if rest_of_line_end != -1:
                            out.append(text[i : rest_of_line_end + 1])
                            i = rest_of_line_end + 1
                            heredoc_delim = heredoc_delim_pending
                            continue
            if ch == "#":
                prev = out[-1] if out else "\n"
                if prev in ("\n", " ", "\t", ";", "&", "|", "("):
                    while i < n and text[i] != "\n":
                        i += 1
                    continue

        out.append(ch)
        i += 1

    return "".join(out)


def _strip_ps1_comments(text: str) -> str:
    """Deterministic char-by-char comment stripper for PowerShell 5.1 scripts."""
    n = len(text)
    i = 0
    out: list[str] = []
    in_single = False
    in_double = False
    in_here_single = False
    in_here_double = False

    while i < n:
        ch = text[i]
        if in_here_single:
            if ch == "'" and i + 1 < n and text[i + 1] == "@":
                out.append("'@")
                in_here_single = False
                i += 2
                continue
            out.append(ch)
            i += 1
            continue

        if in_here_double:
            if ch == '"' and i + 1 < n and text[i + 1] == "@":
                out.append('"@')
                in_here_double = False
                i += 2
                continue
            out.append(ch)
            i += 1
            continue

        if in_single:
            out.append(ch)
            if ch == "'" and i + 1 < n and text[i + 1] == "'":
                out.append("'")
                i += 2
                continue
            if ch == "'":
                in_single = False
            i += 1
            continue

        if in_double:
            out.append(ch)
            if ch == "`" and i + 1 < n:
                out.append(text[i + 1])
                i += 2
                continue
            if ch == '"':
                in_double = False
            i += 1
            continue

        # Outside strings
        if ch == "@" and i + 1 < n and text[i + 1] == "'":
            out.append("@'")
            in_here_single = True
            i += 2
            continue
        if ch == "@" and i + 1 < n and text[i + 1] == '"':
            out.append('@"')
            in_here_double = True
            i += 2
            continue
        if ch == "<" and i + 1 < n and text[i + 1] == "#":
            i += 2
            while i < n:
                if text[i] == "#" and i + 1 < n and text[i + 1] == ">":
                    i += 2
                    break
                if text[i] == "\n":
                    out.append("\n")
                i += 1
            continue
        if ch == "#":
            while i < n and text[i] != "\n":
                i += 1
            continue
        if ch == "'":
            in_single = True
            out.append(ch)
            i += 1
            continue
        if ch == '"':
            in_double = True
            out.append(ch)
            i += 1
            continue

        out.append(ch)
        i += 1

    return "".join(out)


def _strip_c_style_comments(text: str, *, strip_html: bool = False) -> str:
    """Strip /* ... */, // ..., and optionally <!-- ... --> outside quotes."""
    if strip_html:
        text = re.sub(r"<!--.*?-->", "", text, flags=re.DOTALL)
    n = len(text)
    i = 0
    out: list[str] = []
    in_single = False
    in_double = False
    in_tick = False
    escaped = False

    while i < n:
        ch = text[i]
        if escaped:
            out.append(ch)
            escaped = False
            i += 1
            continue
        if ch == "\\" and (in_single or in_double or in_tick):
            out.append(ch)
            escaped = True
            i += 1
            continue
        if ch == "'" and not in_double and not in_tick:
            in_single = not in_single
            out.append(ch)
            i += 1
            continue
        if ch == '"' and not in_single and not in_tick:
            in_double = not in_double
            out.append(ch)
            i += 1
            continue
        if ch == "`" and not in_single and not in_double:
            in_tick = not in_tick
            out.append(ch)
            i += 1
            continue

        if not in_single and not in_double and not in_tick:
            if ch == "/" and i + 1 < n and text[i + 1] == "*":
                i += 2
                while i < n and not (text[i] == "*" and i + 1 < n and text[i + 1] == "/"):
                    if text[i] == "\n":
                        out.append("\n")
                    i += 1
                i += 2
                continue
            if ch == "/" and i + 1 < n and text[i + 1] == "/":
                # Preserve URLs like https://
                if i > 0 and text[i - 1] == ":":
                    out.append(ch)
                    i += 1
                    continue
                while i < n and text[i] != "\n":
                    i += 1
                continue

        out.append(ch)
        i += 1
    return "".join(out)


def _safe_yaml_load(
    text: str, rel_path: str, violations: list[dict[str, Any]]
) -> tuple[Any, bool]:
    if yaml is None:
        return None, True
    try:
        return yaml.safe_load(text), True
    except yaml.YAMLError as exc:
        mark = getattr(exc, "problem_mark", None)
        lineno = (mark.line + 1) if mark is not None else 0
        violations.append({"file": rel_path, "line": lineno, "rule": "yaml_syntax", "message": f"Invalid YAML: {exc}"})
        return None, False


def _check_shell_or_ps1_lines(
    stripped_text: str, rel_path: str, violations: list[dict[str, Any]]
) -> None:
    env_mesa_re = re.compile(
        r"(?:^|[;\s&|\"']|\\n)(?:export\s+|env\s+|\$env:)?(?:MESA_LOADER_DRIVER_OVERRIDE|GALLIUM_DRIVER)\s*=(?!=)\s*[\"']?iris\b",
        re.IGNORECASE,
    )
    env_libva_re = re.compile(
        r"(?:^|[;\s&|\"']|\\n)(?:export\s+|env\s+|\$env:)?LIBVA_DRIVER_NAME\s*=(?!=)\s*[\"']?iHD\b",
        re.IGNORECASE,
    )
    env_dxvk_re = re.compile(
        r"(?:^|[;\s&|\"']|\\n)(?:export\s+|env\s+|\$env:)?DXVK_VER(?:SION)?\s*=(?!=)\s*[\"']?v?2(?:\.[0-9]+)?\b",
        re.IGNORECASE,
    )
    ps_set_env_mesa_re = re.compile(
        r"\[(?:System\.)?Environment\]::SetEnvironmentVariable\s*\(\s*[\"'](?:MESA_LOADER_DRIVER_OVERRIDE|GALLIUM_DRIVER)[\"']\s*,\s*[\"']iris\b",
        re.IGNORECASE,
    )
    ps_set_env_libva_re = re.compile(
        r"\[(?:System\.)?Environment\]::SetEnvironmentVariable\s*\(\s*[\"']LIBVA_DRIVER_NAME[\"']\s*,\s*[\"']iHD\b",
        re.IGNORECASE,
    )
    ps_set_env_dxvk_re = re.compile(
        r"\[(?:System\.)?Environment\]::SetEnvironmentVariable\s*\(\s*[\"']DXVK_VER(?:SION)?[\"']\s*,\s*[\"']v?2(?:\.[0-9]+)?\b",
        re.IGNORECASE,
    )
    pkg_install_re = re.compile(
        r"(?:pacman\s+-S|pacstrap|yay\s+-S|paru\s+-S|pip\s+install|winetricks|curl|wget|Invoke-WebRequest)",
        re.IGNORECASE,
    )
    pkg_bad_re = re.compile(
        r"(?:intel-media-driver|vkd3d-proton|dxvk[-_/]?v?2\.[0-9]+|dxvk20\d\d)",
        re.IGNORECASE,
    )
    log_line_re = re.compile(
        r"^\s*(?:echo|printf|Write-Host|Write-Output|Write-Error|Write-Warning|\[Console\]::Error\.WriteLine)\b",
        re.IGNORECASE,
    )

    for lineno, line in enumerate(stripped_text.splitlines(), start=1):
        s = line.strip()
        if not s:
            continue
        s_no_diag_redir = re.sub(r"(?:\d*>&\d+|\d*>\s*/dev/null)", "", s)
        has_file_redirect = bool(
            re.search(r"(?:>>?|\|\s*(?:sudo\s+)?tee\b|\b(?:Set-Content|Add-Content|Out-File)\b)", s_no_diag_redir, re.IGNORECASE)
        )
        is_benign_log = bool(log_line_re.match(s)) and not has_file_redirect
        if is_benign_log:
            continue

        if env_mesa_re.search(s) or ps_set_env_mesa_re.search(s):
            violations.append({"file": rel_path, "line": lineno, "rule": "no_iris", "message": f"Active iris driver assignment: {s}"})
        if env_libva_re.search(s) or ps_set_env_libva_re.search(s):
            violations.append({"file": rel_path, "line": lineno, "rule": "no_ihd", "message": f"Active iHD VA-API assignment: {s}"})
        if env_dxvk_re.search(s) or ps_set_env_dxvk_re.search(s):
            violations.append({"file": rel_path, "line": lineno, "rule": "no_dxvk_2x", "message": f"Active DXVK 2.x assignment: {s}"})

        if pkg_install_re.search(s) and not re.search(r"pacman\s+-Q", s) and pkg_bad_re.search(s):
            violations.append({"file": rel_path, "line": lineno, "rule": "forbidden_package_or_download", "message": f"Forbidden package/download reference: {s}"})
        elif FORBIDDEN_ARTIFACT_RE.search(s):
            is_guard_stmt = bool(
                (re.match(r"^(?:if|elif)\s+", s) and re.search(r"(?:==|!=|\bgrep\s+-\w*[qE])", s))
                or re.match(r"^(?:\[\[|\[)\s+.*(?:==|!=)", s)
                or re.match(r"^(?:if|elseif)\s*\([^)]*(?:-eq|-ne|-match|-like|==|!=)", s, re.IGNORECASE)
                or (re.search(r"\|\s*grep\s+-\w*q\b", s) and not has_file_redirect and "=" not in s)
            )
            if is_guard_stmt:
                continue
            violations.append({"file": rel_path, "line": lineno, "rule": "forbidden_artifact", "message": f"Forbidden driver/runtime artifact: {s}"})


def _check_package_list(
    text: str, rel_path: str, violations: list[dict[str, Any]]
) -> None:
    for lineno, raw_line in enumerate(text.splitlines(), start=1):
        cleaned = raw_line.split("#", 1)[0].strip()
        if not cleaned:
            continue
        for token in cleaned.split():
            if FORBIDDEN_PKG_RE.match(token):
                violations.append(
                    {
                        "file": rel_path,
                        "line": lineno,
                        "rule": "forbidden_package",
                        "message": f"Forbidden package '{token}' in package list",
                    }
                )


def _check_ini_or_conf(
    text: str, rel_path: str, violations: list[dict[str, Any]]
) -> None:
    is_service = rel_path.endswith(".service")
    is_pacman = Path(rel_path).name == "pacman.conf"
    for lineno, line in _strip_ini_comments(text):
        if is_service and re.match(r"^(?:Description|Documentation)\s*=", line):
            continue
        if is_pacman and re.match(r"^IgnorePkg\s*=", line):
            continue

        # Standard KEY=VALUE or Hyprland env = KEY,VAL
        kv = re.match(r"^([A-Za-z0-9_.-]+)\s*=\s*(.+)$", line)
        if kv:
            k, v = kv.group(1), kv.group(2).strip().strip("\"'")
            if k == "env" and "," in v:
                ek, ev = [p.strip().strip("\"'") for p in v.split(",", 1)]
                k, v = ek, ev
            if k in ("MESA_LOADER_DRIVER_OVERRIDE", "GALLIUM_DRIVER") and re.search(r"\biris\b", v, re.IGNORECASE):
                violations.append({"file": rel_path, "line": lineno, "rule": "no_iris", "message": f"{k} cannot be set to '{v}'"})
            elif k == "LIBVA_DRIVER_NAME" and re.search(r"\biHD\b", v, re.IGNORECASE):
                violations.append({"file": rel_path, "line": lineno, "rule": "no_ihd", "message": f"{k} cannot be set to '{v}'"})
            elif k in ("DXVK_VER", "DXVK_VERSION") and DXVK_2X_VAL_RE.match(v):
                violations.append({"file": rel_path, "line": lineno, "rule": "no_dxvk_2x", "message": f"{k} cannot be set to '{v}'"})

        if FORBIDDEN_ARTIFACT_RE.search(line):
            violations.append({"file": rel_path, "line": lineno, "rule": "forbidden_artifact", "message": f"Forbidden artifact reference: {line}"})


def _walk_structured_data(
    obj: Any, rel_path: str, violations: list[dict[str, Any]], key_path: str = ""
) -> None:
    if isinstance(obj, dict):
        for k, v in obj.items():
            k_str = str(k)
            next_path = f"{key_path}.{k_str}" if key_path else k_str
            if k_str.lower() in DESCRIPTIVE_YAML_KEYS and isinstance(v, str):
                continue
            if k_str in ("MESA_LOADER_DRIVER_OVERRIDE", "GALLIUM_DRIVER") and isinstance(v, str):
                if re.search(r"\biris\b", v, re.IGNORECASE):
                    violations.append({"file": rel_path, "line": 0, "rule": "no_iris", "message": f"{next_path} set to '{v}'"})
            elif k_str == "LIBVA_DRIVER_NAME" and isinstance(v, str):
                if re.search(r"\biHD\b", v, re.IGNORECASE):
                    violations.append({"file": rel_path, "line": 0, "rule": "no_ihd", "message": f"{next_path} set to '{v}'"})
            elif k_str in ("DXVK_VER", "DXVK_VERSION", "dxvk_version") and isinstance(v, (str, int, float)):
                if DXVK_2X_VAL_RE.match(str(v)):
                    violations.append({"file": rel_path, "line": 0, "rule": "no_dxvk_2x", "message": f"{next_path} set to '{v}'"})
            elif k_str == "packages" and isinstance(v, list):
                for item in v:
                    if isinstance(item, str) and FORBIDDEN_PKG_RE.match(item.strip()):
                        violations.append({"file": rel_path, "line": 0, "rule": "forbidden_package", "message": f"Forbidden package '{item}' under {next_path}"})
            elif k_str == "run" and isinstance(v, str):
                _check_shell_or_ps1_lines(_strip_shell_comments(v), rel_path, violations)
            else:
                _walk_structured_data(v, rel_path, violations, next_path)
    elif isinstance(obj, list):
        for idx, item in enumerate(obj):
            _walk_structured_data(item, rel_path, violations, f"{key_path}[{idx}]")
    elif isinstance(obj, str):
        if FORBIDDEN_ARTIFACT_RE.search(obj):
            violations.append({"file": rel_path, "line": 0, "rule": "forbidden_artifact", "message": f"Forbidden artifact at {key_path}: {obj}"})


def _eval_str_expr(
    node: ast.AST,
    symtab: dict[str, str] | None = None,
    scalar_symtab: dict[str, str] | None = None,
) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.Name) and symtab is not None and node.id in symtab:
        return symtab[node.id]
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        left = _eval_str_expr(node.left, symtab, scalar_symtab)
        right = _eval_str_expr(node.right, symtab, scalar_symtab)
        if left is not None and right is not None:
            return left + right
    if isinstance(node, ast.JoinedStr):
        parts: list[str] = []
        for val_node in node.values:
            if isinstance(val_node, ast.Constant) and isinstance(val_node.value, str):
                parts.append(val_node.value)
            elif isinstance(val_node, ast.FormattedValue):
                if val_node.conversion != -1 or val_node.format_spec is not None:
                    return None
                v = val_node.value
                if isinstance(v, ast.Constant) and isinstance(v.value, (str, int, float)) and not isinstance(v.value, bool):
                    parts.append(str(v.value))
                elif isinstance(v, ast.Name) and scalar_symtab is not None and v.id in scalar_symtab:
                    parts.append(scalar_symtab[v.id])
                else:
                    evaluated = _eval_str_expr(v, symtab, scalar_symtab)
                    if evaluated is None:
                        return None
                    parts.append(evaluated)
            else:
                return None
        return "".join(parts)
    if (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "join"
        and len(node.args) == 1
        and not node.keywords
    ):
        sep = _eval_str_expr(node.func.value, symtab, scalar_symtab)
        arg = node.args[0]
        if sep is not None and isinstance(arg, (ast.List, ast.Tuple)):
            items: list[str] = []
            for elt in arg.elts:
                val = _eval_str_expr(elt, symtab, scalar_symtab)
                if val is None:
                    return None
                items.append(val)
            return sep.join(items)
    return None


def _check_python_ast(
    text: str, rel_path: str, violations: list[dict[str, Any]]
) -> None:
    try:
        tree = ast.parse(text, filename=rel_path)
    except SyntaxError as exc:
        violations.append({"file": rel_path, "line": exc.lineno or 0, "rule": "python_syntax", "message": f"SyntaxError: {exc.msg}"})
        return

    # Collect docstring Expr nodes to skip
    docstring_nodes: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            if node.body and isinstance(node.body[0], ast.Expr):
                val = node.body[0].value
                if isinstance(val, ast.Constant) and isinstance(val.value, str):
                    docstring_nodes.add(id(node.body[0]))

    def _check_kv(key: str, val_node: ast.AST, lineno: int, symtab: dict[str, str], scalar_symtab: dict[str, str]) -> None:
        val = _eval_str_expr(val_node, symtab, scalar_symtab)
        if val is None:
            return
        if key in ("MESA_LOADER_DRIVER_OVERRIDE", "GALLIUM_DRIVER") and re.search(r"\biris\b", val, re.IGNORECASE):
            violations.append({"file": rel_path, "line": lineno, "rule": "no_iris", "message": f"Python sets {key}={val!r}"})
        elif key == "LIBVA_DRIVER_NAME" and re.search(r"\biHD\b", val, re.IGNORECASE):
            violations.append({"file": rel_path, "line": lineno, "rule": "no_ihd", "message": f"Python sets {key}={val!r}"})
        elif key in ("DXVK_VER", "DXVK_VERSION", "dxvk_version") and DXVK_2X_VAL_RE.match(val):
            violations.append({"file": rel_path, "line": lineno, "rule": "no_dxvk_2x", "message": f"Python sets {key}={val!r}"})

    def _record_var(name: str, val_node: ast.AST, symtab: dict[str, str], scalar_symtab: dict[str, str]) -> None:
        rhs_val = _eval_str_expr(val_node, symtab, scalar_symtab)
        if rhs_val is not None:
            symtab[name] = rhs_val
            scalar_symtab[name] = rhs_val
        elif isinstance(val_node, ast.Constant) and isinstance(val_node.value, (int, float)) and not isinstance(val_node.value, bool):
            symtab.pop(name, None)
            scalar_symtab[name] = str(val_node.value)
        else:
            symtab.pop(name, None)
            scalar_symtab.pop(name, None)

    def visit(node: ast.AST, in_guard_ctx: bool, symtab: dict[str, str], scalar_symtab: dict[str, str]) -> None:
        if id(node) in docstring_nodes:
            return
        if isinstance(node, (ast.Compare, ast.Raise)):
            in_guard_ctx = True

        if isinstance(node, ast.Assign):
            for tgt in node.targets:
                if isinstance(tgt, ast.Name):
                    _check_kv(tgt.id, node.value, node.lineno, symtab, scalar_symtab)
                    _record_var(tgt.id, node.value, symtab, scalar_symtab)
                elif isinstance(tgt, ast.Subscript):
                    k = _eval_str_expr(tgt.slice, symtab, scalar_symtab)
                    if k is not None:
                        _check_kv(k, node.value, node.lineno, symtab, scalar_symtab)
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name) and node.value is not None:
            _check_kv(node.target.id, node.value, node.lineno, symtab, scalar_symtab)
            _record_var(node.target.id, node.value, symtab, scalar_symtab)
        elif isinstance(node, ast.Dict):
            for k_node, v_node in zip(node.keys, node.values):
                if k_node is not None:
                    k = _eval_str_expr(k_node, symtab, scalar_symtab)
                    if k is not None:
                        _check_kv(k, v_node, getattr(k_node, "lineno", node.lineno), symtab, scalar_symtab)
        elif isinstance(node, ast.keyword) and node.arg is not None:
            _check_kv(node.arg, node.value, node.lineno, symtab, scalar_symtab)
        elif isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            attr = node.func.attr
            if attr in ("setdefault", "putenv") and len(node.args) >= 2:
                k = _eval_str_expr(node.args[0], symtab, scalar_symtab)
                if k is not None:
                    _check_kv(k, node.args[1], node.lineno, symtab, scalar_symtab)
            elif attr == "update" and node.args:
                first = node.args[0]
                if isinstance(first, (ast.List, ast.Tuple)):
                    for item in first.elts:
                        if isinstance(item, (ast.List, ast.Tuple)) and len(item.elts) == 2:
                            k = _eval_str_expr(item.elts[0], symtab, scalar_symtab)
                            if k is not None:
                                _check_kv(k, item.elts[1], getattr(item, "lineno", node.lineno), symtab, scalar_symtab)

        if not in_guard_ctx and not isinstance(node, ast.Name):
            s = _eval_str_expr(node, symtab, scalar_symtab)
            if s is not None and FORBIDDEN_ARTIFACT_RE.search(s):
                violations.append({"file": rel_path, "line": getattr(node, "lineno", 0), "rule": "forbidden_artifact", "message": f"Forbidden artifact literal {s!r}"})
                return

        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            child_sym = symtab.copy()
            child_scalar = scalar_symtab.copy()
        else:
            child_sym = symtab
            child_scalar = scalar_symtab
        for child in ast.iter_child_nodes(node):
            visit(child, in_guard_ctx, child_sym, child_scalar)

    visit(tree, False, {}, {})


def _check_web_or_qml(
    text: str, rel_path: str, violations: list[dict[str, Any]]
) -> None:
    stripped = _strip_c_style_comments(text, strip_html=rel_path.endswith(".html"))
    for lineno, line in enumerate(stripped.splitlines(), start=1):
        if re.search(r"(?:MESA_LOADER_DRIVER_OVERRIDE|GALLIUM_DRIVER)\s*[:=]\s*[\"']?iris\b", line, re.IGNORECASE):
            violations.append({"file": rel_path, "line": lineno, "rule": "no_iris", "message": f"Active iris reference: {line.strip()}"})
        if re.search(r"LIBVA_DRIVER_NAME\s*[:=]\s*[\"']?iHD\b", line, re.IGNORECASE):
            violations.append({"file": rel_path, "line": lineno, "rule": "no_ihd", "message": f"Active iHD reference: {line.strip()}"})
        if re.search(r"(?:DXVK_VER|DXVK_VERSION|dxvk_version)\s*[:=]\s*[\"']?v?2(?:\.[0-9]+)?\b", line, re.IGNORECASE):
            violations.append({"file": rel_path, "line": lineno, "rule": "no_dxvk_2x", "message": f"Active DXVK 2.x reference: {line.strip()}"})
        if FORBIDDEN_ARTIFACT_RE.search(line):
            violations.append({"file": rel_path, "line": lineno, "rule": "forbidden_artifact", "message": f"Forbidden artifact reference: {line.strip()}"})


def _check_cfg_file(
    text: str, rel_path: str, violations: list[dict[str, Any]]
) -> None:
    for lineno, line in _strip_ini_comments(text):
        if re.search(r"(?:MESA_LOADER_DRIVER_OVERRIDE|GALLIUM_DRIVER)\s*=\s*[\"']?iris\b", line, re.IGNORECASE):
            violations.append({"file": rel_path, "line": lineno, "rule": "no_iris", "message": f"Active iris reference in cfg: {line}"})
        if re.search(r"LIBVA_DRIVER_NAME\s*=\s*[\"']?iHD\b", line, re.IGNORECASE):
            violations.append({"file": rel_path, "line": lineno, "rule": "no_ihd", "message": f"Active iHD reference in cfg: {line}"})
        if re.search(r"DXVK_VER(?:SION)?\s*=\s*[\"']?v?2(?:\.[0-9]+)?\b", line, re.IGNORECASE):
            violations.append({"file": rel_path, "line": lineno, "rule": "no_dxvk_2x", "message": f"Active DXVK 2.x reference in cfg: {line}"})
        if FORBIDDEN_ARTIFACT_RE.search(line):
            violations.append({"file": rel_path, "line": lineno, "rule": "forbidden_artifact", "message": f"Forbidden artifact reference in cfg: {line}"})


def _scan_negative_file(path: Path, root: Path, violations: list[dict[str, Any]]) -> None:
    if _is_excluded_from_negative_scan(path, root) or not path.is_file():
        return
    rel = _rel(path, root)
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        violations.append({"file": rel, "line": 0, "rule": "read_error", "message": str(exc)})
        return

    name = path.name
    suffix = path.suffix.lower()

    if name == "packages.x86_64" or name.startswith("packages."):
        _check_package_list(text, rel, violations)
    elif rel.startswith("installer/calamares/") and suffix in (".conf", ".yml", ".yaml"):
        data, ok = _safe_yaml_load(text, rel, violations)
        if ok and data is not None:
            _walk_structured_data(data, rel, violations)
    elif name == "environment" or suffix in (".conf", ".ini", ".service", ".rules"):
        _check_ini_or_conf(text, rel, violations)
    elif suffix == ".cfg":
        _check_cfg_file(text, rel, violations)
    elif suffix in (".yml", ".yaml"):
        data, ok = _safe_yaml_load(text, rel, violations)
        if ok and data is not None:
            _walk_structured_data(data, rel, violations)
    elif suffix == ".json":
        try:
            data = json.loads(text)
            _walk_structured_data(data, rel, violations)
        except json.JSONDecodeError as exc:
            violations.append({"file": rel, "line": exc.lineno, "rule": "json_syntax", "message": str(exc)})
    elif suffix == ".sh" or rel == "iso-profile/airootfs/usr/local/bin/kite-postinstall-hook":
        _check_shell_or_ps1_lines(_strip_shell_comments(text), rel, violations)
    elif suffix == ".ps1":
        _check_shell_or_ps1_lines(_strip_ps1_comments(text), rel, violations)
    elif suffix == ".py":
        _check_python_ast(text, rel, violations)
    elif suffix in (".js", ".html", ".css", ".qml"):
        _check_web_or_qml(text, rel, violations)


def _check_docs(
    root: Path, scope: str, checks_passed: list[str], violations: list[dict[str, Any]]
) -> None:
    required = scope in ("m1", "full")
    agents_path = root / "AGENTS.md"
    skill_path = root / ".agents" / "skills" / "kite-os-builder" / "SKILL.md"
    # In auto scope, validate verbatim SHA-256 only when both verbatim files exist (full repo),
    # so minimal synthetic test fixtures with dummy AGENTS.md prose don't false-fail.
    verify_verbatim = required or (agents_path.is_file() and skill_path.is_file())

    doc_specs = [
        (agents_path, EXPECTED_AGENTS_SHA256, "AGENTS.md"),
        (skill_path, EXPECTED_SKILL_SHA256, "SKILL.md"),
    ]
    if verify_verbatim:
        for path, expected_sha, label in doc_specs:
            rel = _rel(path, root)
            if not path.is_file():
                if required:
                    violations.append({"file": rel, "line": 0, "rule": "missing_file", "message": f"Required verbatim file missing: {rel}"})
                continue
            raw = path.read_bytes()
            if raw.startswith(b"\xef\xbb\xbf"):
                violations.append({"file": rel, "line": 0, "rule": "utf8_bom", "message": f"{label} contains UTF-8 BOM"})
            if b"\r" in raw:
                violations.append({"file": rel, "line": 0, "rule": "crlf", "message": f"{label} contains CR/CRLF line endings"})
            digest = hashlib.sha256(raw).hexdigest()
            allowed_digests = {expected_sha}
            if label == "AGENTS.md":
                allowed_digests.add(EXPECTED_LEGACY_AGENTS_SHA256)
            if digest not in allowed_digests:
                violations.append({"file": rel, "line": 0, "rule": "sha256_mismatch", "message": f"{label} SHA-256 mismatch: got {digest}, expected {expected_sha}"})
            else:
                checks_passed.append(f"verbatim:{rel}")

    if required:
        for req_file in ("README.md", "pyproject.toml"):
            p = root / req_file
            if not p.is_file():
                violations.append({"file": req_file, "line": 0, "rule": "missing_file", "message": f"Required root file missing: {req_file}"})
            else:
                checks_passed.append(f"exists:{req_file}")


def _check_iso_profile_positive(
    root: Path, scope: str, checks_passed: list[str], violations: list[dict[str, Any]]
) -> None:
    iso_dir = root / "iso-profile"
    strict = scope in ("m1", "full")

    env_path = iso_dir / "airootfs" / "etc" / "environment"
    env_d_conf = iso_dir / "airootfs" / "etc" / "environment.d" / "10-kite-haswell.conf"
    env_d_dir = iso_dir / "airootfs" / "etc" / "environment.d"
    extra_confs = sorted(p for p in env_d_dir.glob("*.conf") if p != env_d_conf) if env_d_dir.is_dir() else []

    def _has_pins(p: Path) -> tuple[bool, bool]:
        has_c = False
        has_i = False
        for _, line in _strip_ini_comments(p.read_text(encoding="utf-8", errors="replace")):
            if line == "MESA_LOADER_DRIVER_OVERRIDE=crocus":
                has_c = True
            if line == "LIBVA_DRIVER_NAME=i965":
                has_i = True
        return has_c, has_i

    if strict:
        all_ok = True
        for req_env in (env_path, env_d_conf):
            rel_env = _rel(req_env, root)
            if not req_env.is_file():
                all_ok = False
                violations.append({"file": rel_env, "line": 0, "rule": "missing_file", "message": f"Missing required Haswell environment file: {rel_env}"})
                continue
            c_ok, i_ok = _has_pins(req_env)
            if not c_ok:
                all_ok = False
                violations.append({"file": rel_env, "line": 0, "rule": "missing_crocus", "message": f"Missing active MESA_LOADER_DRIVER_OVERRIDE=crocus in {rel_env}"})
            if not i_ok:
                all_ok = False
                violations.append({"file": rel_env, "line": 0, "rule": "missing_i965", "message": f"Missing active LIBVA_DRIVER_NAME=i965 in {rel_env}"})
        if all_ok:
            checks_passed.append("iso-profile:env-pins:crocus+i965")
    else:
        primary_targets = [p for p in (env_path, env_d_conf) if p.is_file()]
        extra_targets = [p for p in extra_confs if p.is_file()]
        if primary_targets:
            all_ok = True
            for p in primary_targets:
                rel_env = _rel(p, root)
                c_ok, i_ok = _has_pins(p)
                if not c_ok:
                    all_ok = False
                    violations.append({"file": rel_env, "line": 0, "rule": "missing_crocus", "message": f"Missing active MESA_LOADER_DRIVER_OVERRIDE=crocus in {rel_env}"})
                if not i_ok:
                    all_ok = False
                    violations.append({"file": rel_env, "line": 0, "rule": "missing_i965", "message": f"Missing active LIBVA_DRIVER_NAME=i965 in {rel_env}"})
            if all_ok:
                checks_passed.append("iso-profile:env-pins:crocus+i965")
        elif extra_targets:
            found_c = any(_has_pins(p)[0] for p in extra_targets)
            found_i = any(_has_pins(p)[1] for p in extra_targets)
            if not found_c:
                violations.append({"file": "iso-profile/airootfs/etc/environment.d", "line": 0, "rule": "missing_crocus", "message": "Missing active MESA_LOADER_DRIVER_OVERRIDE=crocus"})
            if not found_i:
                violations.append({"file": "iso-profile/airootfs/etc/environment.d", "line": 0, "rule": "missing_i965", "message": "Missing active LIBVA_DRIVER_NAME=i965"})
            if found_c and found_i:
                checks_passed.append("iso-profile:env-pins:crocus+i965")

    pkg_file = iso_dir / "packages.x86_64"
    if not pkg_file.is_file():
        if strict:
            violations.append({"file": "iso-profile/packages.x86_64", "line": 0, "rule": "missing_file", "message": "Missing packages.x86_64"})
    else:
        tokens: set[str] = set()
        for raw_line in pkg_file.read_text(encoding="utf-8", errors="replace").splitlines():
            cleaned = raw_line.split("#", 1)[0].strip()
            tokens.update(cleaned.split())
        required_pkgs = (
            {"mesa", "vulkan-intel", "libva-intel-driver", "linux-cachyos", "btrfs-progs", "pipewire"}
            if strict
            else {"mesa", "libva-intel-driver"}
        )
        missing_pkgs = sorted(required_pkgs - tokens)
        if missing_pkgs:
            violations.append({"file": "iso-profile/packages.x86_64", "line": 0, "rule": "missing_packages", "message": f"Missing required packages: {', '.join(missing_pkgs)}"})
        else:
            checks_passed.append("iso-profile:packages:mesa+libva-intel-driver")

    pacman_conf = iso_dir / "pacman.conf"
    if not pacman_conf.is_file():
        if strict:
            violations.append({"file": "iso-profile/pacman.conf", "line": 0, "rule": "missing_file", "message": "Missing pacman.conf"})
    else:
        pc_text = "\n".join(line for _, line in _strip_ini_comments(pacman_conf.read_text(encoding="utf-8", errors="replace")))
        if "cachyos-v3" not in pc_text or "x86_64_v3" not in pc_text:
            violations.append({"file": "iso-profile/pacman.conf", "line": 0, "rule": "missing_v3_repo", "message": "pacman.conf must declare cachyos-v3 and x86_64_v3"})
        else:
            checks_passed.append("iso-profile:pacman-v3")

    mods_dir = iso_dir / "airootfs" / "etc" / "modules-load.d"
    if strict or mods_dir.is_dir():
        mods_tokens: set[str] = set()
        if mods_dir.is_dir():
            for mf in mods_dir.glob("*.conf"):
                for _, line in _strip_ini_comments(mf.read_text(encoding="utf-8", errors="replace")):
                    mods_tokens.update(line.split())
        missing_mods = sorted({"ntsync", "binder_linux"} - mods_tokens)
        if missing_mods:
            violations.append({"file": "iso-profile/airootfs/etc/modules-load.d", "line": 0, "rule": "missing_modules", "message": f"Missing kernel modules in modules-load.d: {', '.join(missing_mods)}"})
        else:
            checks_passed.append("iso-profile:modules-load:ntsync+binder_linux")

    boot_files: list[Path] = []
    for sub in ("efiboot", "grub", "syslinux"):
        d = iso_dir / sub
        if d.is_dir():
            boot_files.extend(p for p in d.rglob("*") if p.is_file())
    if strict or boot_files:
        boot_text = "\n".join(p.read_text(encoding="utf-8", errors="replace") for p in boot_files)
        missing_kparams = [k for k in ("i915.enable_fbc=1", "i915.fastboot=1", "intel_pstate=active") if k not in boot_text]
        if missing_kparams:
            violations.append({"file": "iso-profile/efiboot", "line": 0, "rule": "missing_kernel_params", "message": f"Bootloader configs missing: {', '.join(missing_kparams)}"})
        else:
            checks_passed.append("iso-profile:bootloaders")


def _check_scripts_positive(
    root: Path, checks_passed: list[str], violations: list[dict[str, Any]]
) -> None:
    scripts_dir = root / "scripts"
    for name in ("test-qemu.sh", "test-qemu.ps1"):
        p = scripts_dir / name
        if not p.is_file():
            violations.append({"file": f"scripts/{name}", "line": 0, "rule": "missing_file", "message": f"Missing {name}"})
            continue
        raw = p.read_text(encoding="utf-8", errors="replace")
        stripped = _strip_shell_comments(raw) if name.endswith(".sh") else _strip_ps1_comments(raw)
        if not re.search(r"['\"]?-cpu['\"]?(?:\s*,\s*|\s+)['\"]?Haswell-noTSX['\"]?", stripped):
            violations.append({"file": f"scripts/{name}", "line": 0, "rule": "missing_haswell_cpu", "message": f"{name} must specify -cpu Haswell-noTSX"})
        else:
            checks_passed.append(f"scripts:{name}:haswell")

    for name in ("build-iso.sh", "build-iso.ps1"):
        p = scripts_dir / name
        if not p.is_file():
            violations.append({"file": f"scripts/{name}", "line": 0, "rule": "missing_file", "message": f"Missing {name}"})
            continue
        raw = p.read_text(encoding="utf-8", errors="replace")
        stripped = _strip_shell_comments(raw) if name.endswith(".sh") else _strip_ps1_comments(raw)
        if "kite-os-folio9480-x86_64_v3.iso" not in stripped:
            violations.append({"file": f"scripts/{name}", "line": 0, "rule": "missing_iso_name", "message": f"{name} must reference kite-os-folio9480-x86_64_v3.iso"})
        else:
            checks_passed.append(f"scripts:{name}:iso-target")


def _check_github_positive(
    root: Path, checks_passed: list[str], violations: list[dict[str, Any]]
) -> None:
    wf = root / ".github" / "workflows" / "build-iso.yml"
    if not wf.is_file():
        violations.append({"file": ".github/workflows/build-iso.yml", "line": 0, "rule": "missing_file", "message": "Missing build-iso.yml workflow"})
        return
    data, ok = _safe_yaml_load(wf.read_text(encoding="utf-8", errors="replace"), ".github/workflows/build-iso.yml", violations)
    if not ok:
        return
    if yaml is not None and (not isinstance(data, dict) or "jobs" not in data):
        violations.append({"file": ".github/workflows/build-iso.yml", "line": 0, "rule": "invalid_workflow", "message": "Invalid workflow YAML"})
        return
    checks_passed.append("github:build-iso.yml")


def _check_hw_tune_positive(
    root: Path, scope: str, checks_passed: list[str], violations: list[dict[str, Any]]
) -> None:
    d = root / "kite-hw-tune"
    chunks: list[str] = []
    has_full_impl = False
    for p in d.rglob("*"):
        if p.is_file() and not _is_excluded_from_negative_scan(p, root) and p.suffix.lower() in (".py", ".sh", ".conf", ".env", ".service", ".rules"):
            if p.suffix.lower() in (".py", ".service"):
                has_full_impl = True
            chunks.append(p.read_text(encoding="utf-8", errors="replace"))
    combined = "\n".join(chunks)
    if scope == "full" or has_full_impl:
        missing = [tok for tok in ("crocus", "i965", "lz4", "zstd", "rotational", "bfq") if tok not in combined]
        if "kyber" not in combined and "none" not in combined:
            missing.append("kyber/none")
    else:
        missing = [tok for tok in ("crocus", "i965") if tok not in combined]
    if missing:
        violations.append({"file": "kite-hw-tune", "line": 0, "rule": "hw_tune_invariants", "message": f"Missing kite-hw-tune tokens: {', '.join(missing)}"})
    else:
        checks_passed.append("kite-hw-tune:invariants:crocus+i965+ram-tiers+storage")


def _check_shell_positive(
    root: Path, checks_passed: list[str], violations: list[dict[str, Any]]
) -> None:
    hypr_dir = root / "kite-shell" / "hypr"
    if not hypr_dir.is_dir():
        violations.append({"file": "kite-shell/hypr", "line": 0, "rule": "missing_dir", "message": "Missing kite-shell/hypr"})
        return
    confs = sorted(hypr_dir.glob("*.conf"))
    cleaned_lines = [
        line
        for p in confs
        for _, line in _strip_ini_comments(p.read_text(encoding="utf-8", errors="replace"))
    ]
    text = "\n".join(cleaned_lines)
    size_m = re.findall(r"^\s*(?:decoration:blur:)?size\s*=\s*(\d+)", text, flags=re.MULTILINE)
    passes_m = re.findall(r"^\s*(?:decoration:blur:)?passes\s*=\s*(\d+)", text, flags=re.MULTILINE)
    xray_ok = bool(re.search(r"^\s*(?:decoration:blur:)?xray\s*=\s*(?:true|yes)\b", text, flags=re.MULTILINE | re.IGNORECASE))
    if not size_m or any(int(v) > 6 for v in size_m):
        violations.append({"file": "kite-shell/hypr", "line": 0, "rule": "blur_size_budget", "message": f"Hyprland blur size must be <= 6 (found {size_m})"})
    if not passes_m or any(int(v) > 2 for v in passes_m):
        violations.append({"file": "kite-shell/hypr", "line": 0, "rule": "blur_passes_budget", "message": f"Hyprland blur passes must be <= 2 (found {passes_m})"})
    if not xray_ok:
        violations.append({"file": "kite-shell/hypr", "line": 0, "rule": "blur_xray", "message": "Hyprland blur xray = true/yes required"})
    if size_m and passes_m and xray_ok and all(int(v) <= 6 for v in size_m) and all(int(v) <= 2 for v in passes_m):
        checks_passed.append("kite-shell:blur-budget:size<=6+passes<=2")


def _check_bridge_positive(
    root: Path, scope: str, checks_passed: list[str], violations: list[dict[str, Any]]
) -> None:
    d = root / "kite-bridge"
    chunks: list[str] = []
    has_full_impl = False
    for p in d.rglob("*"):
        if p.is_file() and not _is_excluded_from_negative_scan(p, root) and p.suffix.lower() in (".py", ".sh", ".json", ".xml"):
            if p.suffix.lower() == ".py":
                has_full_impl = True
            chunks.append(p.read_text(encoding="utf-8", errors="replace"))
    combined = "\n".join(chunks)
    if scope == "full" or has_full_impl:
        required = ("1.10.3", "Haswell-noTSX", "+invtsc", "vendor=GenuineIntel", "persist.waydroid.multi_windows")
    else:
        required = ("1.10.3",)
    missing = [tok for tok in required if tok not in combined]
    if missing:
        violations.append({"file": "kite-bridge", "line": 0, "rule": "bridge_invariants", "message": f"Missing kite-bridge invariants: {', '.join(missing)}"})
    else:
        checks_passed.append("kite-bridge:invariants:dxvk-1.10.3+haswell-kvm+waydroid")


def _check_installer_positive(
    root: Path, scope: str, checks_passed: list[str], violations: list[dict[str, Any]]
) -> None:
    d = root / "installer"
    calamares_dir = d / "calamares"
    found_subvols: dict[str, str] = {}
    btrfs_mount_opts: set[str] = set()
    kernel_params_found: set[str] = set()
    sh_chunks: list[str] = []
    has_boot_or_val = False

    if calamares_dir.is_dir():
        for p in sorted(calamares_dir.rglob("*")):
            if not p.is_file() or _is_excluded_from_negative_scan(p, root):
                continue
            if p.suffix.lower() not in (".conf", ".yml", ".yaml"):
                continue
            if p.name == "bootloader.conf":
                has_boot_or_val = True
            rel = _rel(p, root)
            text = p.read_text(encoding="utf-8", errors="replace")
            if yaml is not None:
                data, ok = _safe_yaml_load(text, rel, violations)
                if not ok or not isinstance(data, dict):
                    continue
                subvols = data.get("btrfsSubvolumes")
                if isinstance(subvols, list):
                    for entry in subvols:
                        if isinstance(entry, dict) and isinstance(entry.get("subvolume"), str):
                            sv = entry["subvolume"].strip().lstrip("/")
                            mp = str(entry.get("mountPoint", "")).strip()
                            if sv:
                                found_subvols[sv] = mp
                mount_opts = data.get("mountOptions")
                if isinstance(mount_opts, list):
                    for entry in mount_opts:
                        if isinstance(entry, dict) and str(entry.get("filesystem", "")).lower() == "btrfs":
                            opts_val = entry.get("options")
                            if isinstance(opts_val, list):
                                btrfs_mount_opts.update(str(o).strip() for o in opts_val)
                kparams = data.get("kernelParams")
                if isinstance(kparams, list):
                    kernel_params_found.update(str(kp).strip() for kp in kparams)

    for p in sorted(d.rglob("*")):
        if p.is_file() and not _is_excluded_from_negative_scan(p, root) and p.suffix.lower() == ".sh":
            if "validation" in p.parts:
                has_boot_or_val = True
            sh_chunks.append(_strip_shell_comments(p.read_text(encoding="utf-8", errors="replace")))

    expected_subvols = {
        "@": "/",
        "@home": "/home",
        "@kitebridge": "/var/lib/kitebridge",
        "@snapshots": "/.snapshots",
    }
    missing: list[str] = []
    for sv, expected_mp in expected_subvols.items():
        if sv not in found_subvols:
            missing.append(sv)
        elif found_subvols[sv] and found_subvols[sv] != expected_mp:
            missing.append(f"{sv}->{expected_mp}")

    for opt in ("compress=zstd:1", "noatime"):
        if opt not in btrfs_mount_opts:
            missing.append(opt)

    if scope == "full" or has_boot_or_val:
        sh_combined = "\n".join(sh_chunks)
        for kp in ("i915.enable_fbc=1", "i915.fastboot=1", "intel_pstate=active"):
            if kp not in kernel_params_found and kp not in sh_combined:
                missing.append(kp)

    if missing:
        violations.append({"file": "installer", "line": 0, "rule": "installer_invariants", "message": f"Missing installer invariants: {', '.join(missing)}"})
    else:
        checks_passed.append("installer:invariants:btrfs(@,@home,@kitebridge,@snapshots)+compress=zstd:1+noatime")


def _check_kite_ai_positive(
    root: Path, checks_passed: list[str], violations: list[dict[str, Any]]
) -> None:
    d = root / "kite-ai"
    # Check 18: Privacy guardrail (.kiteignore + privacy.py)
    kiteignore = d / ".kiteignore"
    privacy_py = d / "src" / "kite_ai" / "privacy.py"
    priv_text = ""
    if kiteignore.is_file():
        priv_text += kiteignore.read_text(encoding="utf-8", errors="replace")
    if privacy_py.is_file():
        priv_text += "\n" + privacy_py.read_text(encoding="utf-8", errors="replace")
    missing_priv = [tok for tok in (".ssh", ".gnupg", ".env", "shadow", "firefox", "chromium") if tok not in priv_text]
    if not kiteignore.is_file() or not privacy_py.is_file() or missing_priv:
        violations.append({"file": "kite-ai", "line": 0, "rule": "kite_ai_privacy", "message": f"Kite AI privacy guardrail incomplete (missing: {', '.join(missing_priv) or 'files'})"})
    else:
        checks_passed.append("kite-ai:privacy:kiteignore-guardrail")

    # Check 19: Zero-idle-daemon RAM (socket activation + idle timer + ionice -c 3, never boot-enabled daemon)
    sock = d / "systemd" / "kite-aid.socket"
    timer = d / "systemd" / "kite-index.timer"
    idx_svc = d / "systemd" / "kite-index.service"
    cust_sh = root / "iso-profile" / "airootfs" / "root" / "customize_airootfs.sh"
    cust_text = cust_sh.read_text(encoding="utf-8", errors="replace") if cust_sh.is_file() else ""
    idx_text = idx_svc.read_text(encoding="utf-8", errors="replace") if idx_svc.is_file() else ""
    persistent_enabled = bool(re.search(r"systemctl\s+enable[^\n]*\bkite-aid\.service\b", cust_text))
    if (
        not sock.is_file()
        or not timer.is_file()
        or "ionice -c 3" not in idx_text
        or persistent_enabled
    ):
        violations.append({"file": "kite-ai/systemd", "line": 0, "rule": "kite_ai_zero_daemon_ram", "message": "Kite AI must use kite-aid.socket + kite-index.timer with ionice -c 3 and never enable kite-aid.service at boot"})
    else:
        checks_passed.append("kite-ai:zero-daemon-ram:socket-activation")

    # Check 20: Sub-400 token cloud budget + SYSTEM_PREFIX + F1..F10 aliasing
    init_py = d / "src" / "kite_ai" / "__init__.py"
    schema_py = d / "src" / "kite_ai" / "providers" / "schema.py"
    alias_py = d / "src" / "kite_ai" / "compress" / "aliaser.py"
    budget_ok = init_py.is_file() and "DEFAULT_MAX_INPUT_TOKENS = 400" in init_py.read_text(encoding="utf-8", errors="replace")
    prefix_ok = schema_py.is_file() and "SYSTEM_PREFIX" in schema_py.read_text(encoding="utf-8", errors="replace")
    alias_ok = alias_py.is_file() and 'f"F{idx}"' in alias_py.read_text(encoding="utf-8", errors="replace")
    if not (budget_ok and prefix_ok and alias_ok):
        violations.append({"file": "kite-ai/src/kite_ai", "line": 0, "rule": "kite_ai_token_budget", "message": "Kite AI must enforce DEFAULT_MAX_INPUT_TOKENS = 400, static SYSTEM_PREFIX, and F1..Fn path aliasing"})
    else:
        checks_passed.append("kite-ai:token-budget:sub-400-cap")


def run_checks(root: Path, scope: str) -> dict[str, Any]:
    violations: list[dict[str, Any]] = []
    checks_passed: list[str] = []

    if scope == "m1":
        required_mods = M1_MODULES
        target_mods = M1_MODULES
    elif scope == "full":
        required_mods = ALL_MODULES
        target_mods = ALL_MODULES
    else:
        required_mods = ()
        target_mods = ALL_MODULES

    active_modules = [m for m in target_mods if (root / m).is_dir()]

    if scope == "auto" and not active_modules:
        violations.append({"file": ".", "line": 0, "rule": "no_active_modules", "message": f"No KITE_OS module directories found under {root}"})

    for mod in required_mods:
        if not (root / mod).is_dir():
            violations.append({"file": mod, "line": 0, "rule": "missing_module", "message": f"Required module directory missing for scope '{scope}': {mod}"})

    _check_docs(root, scope=scope, checks_passed=checks_passed, violations=violations)

    if "iso-profile" in active_modules:
        _check_iso_profile_positive(root, scope, checks_passed, violations)
    if "scripts" in active_modules:
        _check_scripts_positive(root, checks_passed, violations)
    if ".github" in active_modules:
        _check_github_positive(root, checks_passed, violations)
    if "kite-hw-tune" in active_modules:
        _check_hw_tune_positive(root, scope, checks_passed, violations)
    if "kite-shell" in active_modules:
        _check_shell_positive(root, checks_passed, violations)
    if "kite-bridge" in active_modules:
        _check_bridge_positive(root, scope, checks_passed, violations)
    if "kite-ai" in active_modules:
        _check_kite_ai_positive(root, checks_passed, violations)
    if "installer" in active_modules:
        _check_installer_positive(root, scope, checks_passed, violations)

    # Negative invariant scan across active module trees
    neg_before = len(violations)
    for mod in active_modules:
        mod_dir = root / mod
        for p in sorted(mod_dir.rglob("*")):
            if p.is_file():
                _scan_negative_file(p, root, violations)
    if active_modules and len(violations) == neg_before:
        checks_passed.append("negative-scan:no-iris+no-iHD+no-dxvk-2x+no-vkd3d-proton")

    return {
        "ok": len(violations) == 0,
        "scope": scope,
        "root": str(root),
        "active_modules": active_modules,
        "checks_passed": checks_passed,
        "violations": violations,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Verify KITE_OS Folio 9480m hardware & workspace invariants.")
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parent.parent, help="Repository root path")
    parser.add_argument("--scope", choices=("auto", "m1", "full"), default="auto", help="Verification scope")
    parser.add_argument("--require-all", action="store_true", help="Alias for --scope full")
    parser.add_argument("--json", action="store_true", dest="json_output", help="Emit JSON output")
    args = parser.parse_args(argv)

    root = args.root.resolve()
    if not root.is_dir():
        if args.json_output:
            print(json.dumps({"ok": False, "error": f"Root path is not a directory: {root}"}))
        else:
            print(f"Error: root path is not a directory: {root}", file=sys.stderr)
        return 2

    scope = "full" if args.require_all else args.scope
    result = run_checks(root, scope)

    if args.json_output:
        print(json.dumps(result, indent=2))
    else:
        status = "PASS" if result["ok"] else "FAIL"
        print(f"[check_invariants] {status} (scope={scope}, active_modules={result['active_modules']}, checks={len(result['checks_passed'])}, violations={len(result['violations'])})")
        for v in result["violations"]:
            loc = f"{v['file']}:{v['line']}" if v["line"] else v["file"]
            print(f"  - [{v['rule']}] {loc}: {v['message']}", file=sys.stderr)

    return 0 if result["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
