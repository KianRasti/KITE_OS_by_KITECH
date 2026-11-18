"""Zero-dependency metadata, Markdown/PDF headings, and Python/JS AST/symbol extractor."""

from __future__ import annotations

import ast
import re
from dataclasses import dataclass
from pathlib import Path

from ..models import PlatformBadge

_MD_HEADING_RE = re.compile(r"^\s{0,3}#{1,6}\s+(.+?)\s*#*$", re.MULTILINE)
_JS_SYMBOL_RE = re.compile(
    r"(?:export\s+(?:default\s+)?)?(?:async\s+)?(?:function|class|const|let|var)\s+([A-Za-z_$][A-Za-z0-9_$]*)"
)
_QML_PROP_RE = re.compile(r"^\s*(?:property\s+\w+|function|signal)\s+([A-Za-z_][A-Za-z0-9_]*)", re.MULTILINE)
_PDF_TITLE_RE = re.compile(rb"/Title\s*\(([^)]{1,200})\)")
_PDF_TEXT_RE = re.compile(rb"\(([^()\\]{3,120})\)\s*Tj")

_CODE_EXTS = {
    ".py", ".js", ".ts", ".jsx", ".tsx", ".mjs", ".cjs",
    ".qml", ".c", ".cpp", ".h", ".hpp", ".ino", ".rs",
    ".go", ".sh", ".ps1", ".sql", ".css", ".html", ".json",
    ".yaml", ".yml", ".toml", ".conf",
}
_WIN_EXTS = {".exe", ".msi", ".bat", ".cmd", ".lnk"}
_ANDROID_EXTS = {".apk", ".aab"}
_MACOS_EXTS = {".dmg", ".pkg", ".app"}

MAX_READ_BYTES = 262_144


@dataclass(frozen=True)
class ExtractedContent:
    """Structured local extraction result used for FTS5, SimHash, and TextRank."""

    file_name: str
    platform_badge: PlatformBadge
    headings: tuple[str, ...]
    symbols: tuple[str, ...]
    text_sample: str


def infer_platform_badge(path: str | Path) -> PlatformBadge:
    """Map file extension to canonical KITE_OS Spotlight platform badge."""
    p = Path(path)
    ext = p.suffix.lower()
    if ext in _WIN_EXTS:
        return "[Win]"
    if ext in _ANDROID_EXTS:
        return "[Android]"
    if ext in _MACOS_EXTS:
        return "[macOS]"
    if ext in _CODE_EXTS:
        return "[Code]"
    return "[Doc]"


def _extract_python_symbols(text: str) -> tuple[str, ...]:
    symbols: list[str] = []
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return ()
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            symbols.append(node.name)
    return tuple(dict.fromkeys(symbols))[:40]


def _extract_pdf_text(raw: bytes) -> tuple[tuple[str, ...], str]:
    titles = [m.decode("latin-1", errors="replace").strip() for m in _PDF_TITLE_RE.findall(raw)]
    chunks = [m.decode("latin-1", errors="replace").strip() for m in _PDF_TEXT_RE.findall(raw)]
    if not titles and not chunks:
        # Fallback: extract printable ASCII words from PDF header/body
        ascii_text = re.sub(rb"[^\x20-\x7e\n]+", b" ", raw[:65536]).decode("ascii", errors="replace")
        return (), ascii_text
    headings = tuple(dict.fromkeys([t for t in titles if t]))[:12]
    body = " ".join(titles + chunks)
    return headings, body


def extract_content(path: str | Path, *, raw_bytes: bytes | None = None) -> ExtractedContent:
    """Extract headings, code symbols, and bounded text without loading huge binaries."""
    p = Path(path)
    badge = infer_platform_badge(p)
    ext = p.suffix.lower()

    if raw_bytes is None:
        if p.is_file():
            with p.open("rb") as fh:
                data = fh.read(MAX_READ_BYTES)
        else:
            data = b""
    else:
        data = raw_bytes[:MAX_READ_BYTES]

    if ext in _WIN_EXTS | _ANDROID_EXTS | _MACOS_EXTS:
        return ExtractedContent(
            file_name=p.name,
            platform_badge=badge,
            headings=(),
            symbols=(),
            text_sample=p.stem.replace("_", " ").replace("-", " "),
        )

    if ext == ".pdf" or data.startswith(b"%PDF"):
        pdf_headings, pdf_body = _extract_pdf_text(data)
        return ExtractedContent(
            file_name=p.name,
            platform_badge="[Doc]",
            headings=pdf_headings,
            symbols=(),
            text_sample=f"{p.stem} {pdf_body}".strip(),
        )

    # Skip arbitrary non-text binaries
    if b"\x00" in data[:4096]:
        return ExtractedContent(
            file_name=p.name,
            platform_badge=badge,
            headings=(),
            symbols=(),
            text_sample=p.stem.replace("_", " ").replace("-", " "),
        )

    text = data.decode("utf-8", errors="replace")
    headings: tuple[str, ...] = ()
    symbols: tuple[str, ...] = ()

    if ext in (".md", ".markdown", ".txt", ".rst"):
        headings = tuple(m.strip() for m in _MD_HEADING_RE.findall(text))[:20]
    elif ext == ".py":
        symbols = _extract_python_symbols(text)
    elif ext in (".js", ".ts", ".jsx", ".tsx", ".mjs", ".cjs", ".ino"):
        symbols = tuple(dict.fromkeys(_JS_SYMBOL_RE.findall(text)))[:40]
    elif ext == ".qml":
        symbols = tuple(dict.fromkeys(_QML_PROP_RE.findall(text)))[:40]

    return ExtractedContent(
        file_name=p.name,
        platform_badge=badge,
        headings=headings,
        symbols=symbols,
        text_sample=text,
    )
