"""Injectable OS boundary abstractions and Linux/Directory/Fake implementations."""

from __future__ import annotations

import os
import posixpath
import shutil
import subprocess
import tempfile
import time
from collections.abc import Iterable, Mapping, Sequence
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Protocol, runtime_checkable

from kite_hw_tune.models import CmdResult


def normalize_posix_path(path: str) -> str:
    """Normalize a virtual Linux path using POSIX forward slashes."""
    replaced = path.replace("\\", "/")
    normed = posixpath.normpath(replaced)
    if not normed.startswith("/"):
        normed = "/" + normed
    return normed


def _resolve_under_root(root: Path, virtual_path: str, prefix: str) -> Path:
    """Map a virtual /proc or /sys path safely onto a host root directory."""
    normed = normalize_posix_path(virtual_path)
    prefix_norm = normalize_posix_path(prefix)
    if normed == prefix_norm:
        rel = ""
    elif normed.startswith(prefix_norm + "/"):
        rel = normed[len(prefix_norm) + 1 :]
    else:
        rel = normed.lstrip("/")

    pure = PurePosixPath(rel) if rel else PurePosixPath(".")
    parts = [part for part in pure.parts if part not in ("", ".", "/")]
    if any(part == ".." for part in parts):
        raise ValueError(f"Path traversal not allowed: {virtual_path!r}")

    target = root
    for part in parts:
        target = target / part
    return target


def expand_user_path(path: str) -> Path:
    """Expand ~/ paths consistently across Linux and Windows test environments."""
    norm = path.replace("\\", "/")
    if norm == "~" or norm.startswith("~/"):
        rest = norm[2:] if norm.startswith("~/") else ""
        if rest.startswith(".config/") and os.environ.get("XDG_CONFIG_HOME"):
            return Path(os.environ["XDG_CONFIG_HOME"]) / rest[len(".config/") :]
        home_env = os.environ.get("HOME")
        base = Path(home_env) if home_env else Path.home()
        return base / rest if rest else base
    return Path(path)


@runtime_checkable
class ProcFs(Protocol):
    def read_text(self, path: str) -> str | None: ...
    def exists(self, path: str) -> bool: ...


@runtime_checkable
class SysFs(Protocol):
    def read_text(self, path: str) -> str | None: ...
    def write_text(self, path: str, value: str) -> bool: ...
    def exists(self, path: str) -> bool: ...
    def list_dir(self, path: str) -> list[str]: ...


@runtime_checkable
class CmdRunner(Protocol):
    def run(
        self,
        argv: Sequence[str],
        *,
        check: bool = False,
        env: Mapping[str, str] | None = None,
    ) -> CmdResult: ...

    def which(self, binary: str) -> str | None: ...


@runtime_checkable
class EnvWriter(Protocol):
    def read_text(self, path: str) -> str | None: ...
    def write_text(self, path: str, content: str) -> None: ...
    def exists(self, path: str) -> bool: ...


@runtime_checkable
class Clock(Protocol):
    def now_iso(self) -> str: ...
    def monotonic(self) -> float: ...


class DirectoryProcFs:
    """Directory-backed ProcFs reading from a host directory."""

    def __init__(self, root: Path | str = Path("/proc")) -> None:
        self.root = Path(root)

    def read_text(self, path: str) -> str | None:
        target = _resolve_under_root(self.root, path, "/proc")
        try:
            return target.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            return None

    def exists(self, path: str) -> bool:
        target = _resolve_under_root(self.root, path, "/proc")
        return target.exists()


class LinuxProcFs(DirectoryProcFs):
    """Production Linux /proc reader."""

    def __init__(self, root: Path | str = Path("/proc")) -> None:
        super().__init__(root)


class FakeProcFs:
    """In-memory ProcFs implementation for unit testing."""

    def __init__(self, files: Mapping[str, str] | None = None) -> None:
        self.files: dict[str, str] = {}
        if files:
            for k, v in files.items():
                self.files[self._normalize_key(k)] = v

    @staticmethod
    def _normalize_key(path: str) -> str:
        norm = normalize_posix_path(path)
        if not norm.startswith("/proc/") and norm != "/proc":
            norm = normalize_posix_path("/proc" + norm)
        return norm

    def read_text(self, path: str) -> str | None:
        return self.files.get(self._normalize_key(path))

    def exists(self, path: str) -> bool:
        key = self._normalize_key(path)
        if key in self.files:
            return True
        prefix = key.rstrip("/") + "/"
        return any(k.startswith(prefix) for k in self.files)


class DirectorySysFs:
    """Directory-backed SysFs reading/writing inside a host directory."""

    def __init__(self, root: Path | str = Path("/sys"), *, dry_run: bool = False) -> None:
        self.root = Path(root)
        self.dry_run = dry_run
        self.writes: list[tuple[str, str]] = []

    def read_text(self, path: str) -> str | None:
        target = _resolve_under_root(self.root, path, "/sys")
        try:
            return target.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            return None

    def write_text(self, path: str, value: str) -> bool:
        norm = normalize_posix_path(path)
        if not norm.startswith("/sys"):
            norm = normalize_posix_path("/sys" + norm)
        if self.dry_run:
            return False
        target = _resolve_under_root(self.root, norm, "/sys")
        if not target.exists():
            return False
        try:
            with target.open("w", encoding="utf-8", newline="\n") as fh:
                fh.write(value)
        except OSError:
            return False
        self.writes.append((norm, value))
        return True

    def exists(self, path: str) -> bool:
        target = _resolve_under_root(self.root, path, "/sys")
        return target.exists()

    def list_dir(self, path: str) -> list[str]:
        target = _resolve_under_root(self.root, path, "/sys")
        if not target.is_dir():
            return []
        return sorted(entry.name for entry in target.iterdir())


class LinuxSysFs(DirectorySysFs):
    """Production Linux /sys reader/writer."""

    def __init__(self, root: Path | str = Path("/sys"), *, dry_run: bool = False) -> None:
        super().__init__(root, dry_run=dry_run)


class FakeSysFs:
    """In-memory SysFs implementation with automatic directory listing."""

    def __init__(
        self,
        files: Mapping[str, str] | None = None,
        *,
        readonly_paths: Iterable[str] | None = None,
        dry_run: bool = False,
    ) -> None:
        self.files: dict[str, str] = {}
        self.readonly_paths: set[str] = {
            self._normalize_key(p) for p in (readonly_paths or ())
        }
        self.dry_run = dry_run
        self.writes: list[tuple[str, str]] = []
        if files:
            for k, v in files.items():
                self.files[self._normalize_key(k)] = v

    @staticmethod
    def _normalize_key(path: str) -> str:
        norm = normalize_posix_path(path)
        if not norm.startswith("/sys/") and norm != "/sys":
            norm = normalize_posix_path("/sys" + norm)
        return norm

    def read_text(self, path: str) -> str | None:
        return self.files.get(self._normalize_key(path))

    def write_text(self, path: str, value: str) -> bool:
        key = self._normalize_key(path)
        if self.dry_run or key in self.readonly_paths or key not in self.files:
            return False
        self.files[key] = value
        self.writes.append((key, value))
        return True

    def exists(self, path: str) -> bool:
        key = self._normalize_key(path)
        if key in self.files:
            return True
        prefix = key.rstrip("/") + "/"
        return any(k.startswith(prefix) for k in self.files)

    def list_dir(self, path: str) -> list[str]:
        prefix = self._normalize_key(path).rstrip("/") + "/"
        children: set[str] = set()
        for key in self.files:
            if key.startswith(prefix):
                remainder = key[len(prefix) :]
                if remainder:
                    children.add(remainder.split("/", 1)[0])
        return sorted(children)


class LinuxCmdRunner:
    """Production command runner wrapping subprocess.run."""

    def __init__(self, *, dry_run: bool = False) -> None:
        self.dry_run = dry_run
        self.history: list[tuple[str, ...]] = []

    def run(
        self,
        argv: Sequence[str],
        *,
        check: bool = False,
        env: Mapping[str, str] | None = None,
    ) -> CmdResult:
        cmd_tuple = tuple(argv)
        self.history.append(cmd_tuple)
        if self.dry_run:
            return CmdResult(argv=cmd_tuple, returncode=0)

        merged_env: dict[str, str] | None = None
        if env is not None:
            merged_env = dict(os.environ)
            merged_env.update(env)

        proc = subprocess.run(
            list(cmd_tuple),
            capture_output=True,
            text=True,
            env=merged_env,
            check=False,
        )
        if check and proc.returncode != 0:
            raise subprocess.CalledProcessError(
                proc.returncode,
                list(cmd_tuple),
                output=proc.stdout,
                stderr=proc.stderr,
            )
        return CmdResult(
            argv=cmd_tuple,
            returncode=proc.returncode,
            stdout=proc.stdout,
            stderr=proc.stderr,
        )

    def which(self, binary: str) -> str | None:
        return shutil.which(binary)


class FakeCmdRunner:
    """In-memory command runner recording invocations for unit tests."""

    DEFAULT_BINS = frozenset(
        {"zramctl", "mkswap", "swapon", "swapoff", "sysctl", "iw", "udevadm"}
    )

    def __init__(
        self,
        stubs: Mapping[tuple[str, ...], CmdResult] | None = None,
        *,
        available_bins: Iterable[str] | None = None,
        dry_run: bool = False,
    ) -> None:
        self.stubs: dict[tuple[str, ...], CmdResult] = dict(stubs or {})
        self.available_bins: set[str] = (
            set(available_bins) if available_bins is not None else set(self.DEFAULT_BINS)
        )
        self.dry_run = dry_run
        self.history: list[tuple[str, ...]] = []

    def run(
        self,
        argv: Sequence[str],
        *,
        check: bool = False,
        env: Mapping[str, str] | None = None,
    ) -> CmdResult:
        cmd_tuple = tuple(argv)
        self.history.append(cmd_tuple)
        if self.dry_run:
            return CmdResult(argv=cmd_tuple, returncode=0)

        result = self.stubs.get(cmd_tuple, CmdResult(argv=cmd_tuple, returncode=0))
        if check and result.returncode != 0:
            raise subprocess.CalledProcessError(
                result.returncode,
                list(cmd_tuple),
                output=result.stdout,
                stderr=result.stderr,
            )
        return result

    def which(self, binary: str) -> str | None:
        if binary in self.available_bins:
            return f"/usr/bin/{binary}"
        return None


class RealEnvWriter:
    """Atomic UTF-8 LF-only file reader/writer."""

    def __init__(self, *, dry_run: bool = False) -> None:
        self.dry_run = dry_run
        self.written: dict[str, str] = {}

    def read_text(self, path: str) -> str | None:
        target = expand_user_path(path)
        try:
            return target.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            return None

    def exists(self, path: str) -> bool:
        return expand_user_path(path).exists()

    def write_text(self, path: str, content: str) -> None:
        normalized_content = content.replace("\r\n", "\n")
        if self.dry_run:
            return
        target = expand_user_path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp_name = tempfile.mkstemp(
            prefix=".kite-tmp-",
            dir=str(target.parent),
            text=True,
        )
        tmp_path = Path(tmp_name)
        try:
            with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as fh:
                fh.write(normalized_content)
            os.replace(tmp_path, target)
            if os.name == "posix":
                os.chmod(target, 0o644)
        except Exception:
            if tmp_path.exists():
                tmp_path.unlink(missing_ok=True)
            raise
        self.written[target.as_posix()] = normalized_content


class FakeEnvWriter:
    """In-memory file reader/writer for unit tests."""

    def __init__(
        self,
        files: Mapping[str, str] | None = None,
        *,
        dry_run: bool = False,
    ) -> None:
        self.files: dict[str, str] = {}
        self.dry_run = dry_run
        self.written: dict[str, str] = {}
        if files:
            for k, v in files.items():
                self.files[self._key(k)] = v

    @staticmethod
    def _key(path: str) -> str:
        return path.replace("\\", "/")

    def read_text(self, path: str) -> str | None:
        return self.files.get(self._key(path))

    def exists(self, path: str) -> bool:
        return self._key(path) in self.files

    def write_text(self, path: str, content: str) -> None:
        if self.dry_run:
            return
        key = self._key(path)
        normalized = content.replace("\r\n", "\n")
        self.files[key] = normalized
        self.written[key] = normalized


class SystemClock:
    """Production system clock."""

    def now_iso(self) -> str:
        return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    def monotonic(self) -> float:
        return time.monotonic()


class FakeClock:
    """Deterministic clock for tests."""

    def __init__(
        self,
        iso: str = "2026-11-17T00:00:00Z",
        monotonic_sec: float = 0.0,
    ) -> None:
        self._iso = iso
        self._monotonic = monotonic_sec

    def now_iso(self) -> str:
        return self._iso

    def monotonic(self) -> float:
        return self._monotonic
