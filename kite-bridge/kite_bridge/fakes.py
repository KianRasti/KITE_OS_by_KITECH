"""Complete offline test doubles (fakes) for Windows-host unit & E2E testing."""

from __future__ import annotations

import fnmatch
import os
import shutil
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Any, Callable, Mapping, Sequence

from .models import CommandResult, HwProfile, MountRecord, QmpError


def _norm_posix(path: str) -> str:
    p = path.replace("\\", "/")
    if not p:
        return "/"
    return str(PurePosixPath(p))


@dataclass(frozen=True)
class RecordedCall:
    argv: tuple[str, ...]
    env: dict[str, str]
    cwd: str | None
    kind: str = "run"


class FakeProcessRunner:
    """In-memory ProcessRunner recording all calls without spawning processes."""

    def __init__(
        self,
        *,
        available_binaries: Mapping[str, str] | None = None,
        handlers: Sequence[tuple[Callable[[Sequence[str]], bool], Callable[[Sequence[str], Mapping[str, str] | None, str | None], CommandResult]]] | None = None,
        default_returncode: int = 0,
    ) -> None:
        self.available_binaries: dict[str, str] = dict(available_binaries or {})
        self.handlers: list[tuple[Callable[[Sequence[str]], bool], Callable[[Sequence[str], Mapping[str, str] | None, str | None], CommandResult]]] = list(handlers or [])
        self.default_returncode = default_returncode
        self.invocations: list[RecordedCall] = []
        self._next_pid = 41000

    def register_binary(self, name: str, resolved_path: str | None = None) -> None:
        self.available_binaries[name] = resolved_path or f"/usr/bin/{name}"

    def add_handler(
        self,
        predicate: Callable[[Sequence[str]], bool],
        handler: Callable[[Sequence[str], Mapping[str, str] | None, str | None], CommandResult],
    ) -> None:
        self.handlers.append((predicate, handler))

    def set_result(self, prefix: str, *, returncode: int = 0, stdout: str = "", stderr: str = "") -> None:
        self.add_handler(
            lambda argv, _p=prefix: bool(argv) and (PurePosixPath(argv[0]).name == _p or argv[0] == _p),
            lambda argv, _env, _cwd, _rc=returncode, _out=stdout, _err=stderr: CommandResult(
                argv=tuple(argv), returncode=_rc, stdout=_out, stderr=_err
            ),
        )

    def run(
        self,
        argv: Sequence[str],
        *,
        env: Mapping[str, str] | None = None,
        cwd: str | None = None,
        check: bool = False,
        timeout: float | None = None,
    ) -> CommandResult:
        argv_list = list(argv)
        self.invocations.append(
            RecordedCall(
                argv=tuple(argv_list),
                env=dict(env or {}),
                cwd=cwd,
                kind="run",
            )
        )
        res: CommandResult | None = None
        for predicate, handler in self.handlers:
            if predicate(argv_list):
                res = handler(argv_list, env, cwd)
                break
        if res is None:
            res = CommandResult(argv=tuple(argv_list), returncode=self.default_returncode)
        if check and res.returncode != 0:
            raise RuntimeError(f"Command {argv_list} exited with {res.returncode}: {res.stderr}")
        return res

    def spawn(
        self,
        argv: Sequence[str],
        *,
        env: Mapping[str, str] | None = None,
        cwd: str | None = None,
    ) -> int:
        argv_list = list(argv)
        self.invocations.append(
            RecordedCall(
                argv=tuple(argv_list),
                env=dict(env or {}),
                cwd=cwd,
                kind="spawn",
            )
        )
        pid = self._next_pid
        self._next_pid += 1
        return pid

    def which(self, binary: str) -> str | None:
        if binary in self.available_binaries:
            return self.available_binaries[binary]
        for path_val in self.available_binaries.values():
            if path_val == binary:
                return path_val
        return None


@dataclass
class DeviceEntry:
    kind: str = "char"  # "char", "file", "dir"
    rw: bool = True
    readable: bool = True
    content: bytes = b""


class FakeSystemProbe:
    """In-memory SystemProbe simulating /dev/*, /proc/*, and /sys/*."""

    def __init__(
        self,
        *,
        root_user: bool = False,
        mem_mb: int | None = None,
    ) -> None:
        self._root = root_user
        self._mem_mb = mem_mb
        self.devices: dict[str, DeviceEntry] = {}
        self.files: dict[str, bytes] = {}
        self.dirs: set[str] = {"/"}

    def add_char_device(self, path: str, *, rw: bool = True) -> None:
        norm = _norm_posix(path)
        self.devices[norm] = DeviceEntry(kind="char", rw=rw, readable=True)
        self._ensure_parents(norm)

    def add_dir(self, path: str) -> None:
        norm = _norm_posix(path)
        self.dirs.add(norm)
        self._ensure_parents(norm)

    def add_file(self, path: str, data: str | bytes, *, rw: bool = True) -> None:
        norm = _norm_posix(path)
        raw = data.encode("utf-8") if isinstance(data, str) else data
        self.files[norm] = raw
        self.devices[norm] = DeviceEntry(kind="file", rw=rw, readable=True, content=raw)
        self._ensure_parents(norm)

    def _ensure_parents(self, norm: str) -> None:
        p = PurePosixPath(norm).parent
        while str(p) not in ("", "."):
            self.dirs.add(str(p))
            if str(p) == "/":
                break
            p = p.parent

    def exists(self, path: str) -> bool:
        norm = _norm_posix(path)
        return norm in self.devices or norm in self.files or norm in self.dirs

    def is_char_device(self, path: str) -> bool:
        norm = _norm_posix(path)
        entry = self.devices.get(norm)
        return entry is not None and entry.kind == "char"

    def is_dir(self, path: str) -> bool:
        norm = _norm_posix(path)
        if norm in self.dirs:
            return True
        entry = self.devices.get(norm)
        return entry is not None and entry.kind == "dir"

    def access_rw(self, path: str) -> bool:
        norm = _norm_posix(path)
        entry = self.devices.get(norm)
        if entry is None:
            return False
        return entry.rw

    def read_text(self, path: str) -> str:
        return self.read_bytes(path).decode("utf-8")

    def read_bytes(self, path: str, limit: int | None = None) -> bytes:
        norm = _norm_posix(path)
        if norm not in self.files:
            raise FileNotFoundError(norm)
        data = self.files[norm]
        return data if limit is None else data[:limit]

    def read_head_tail(self, path: str, head: int = 4096, tail: int = 512) -> tuple[bytes, bytes, int]:
        norm = _norm_posix(path)
        if norm not in self.files:
            raise FileNotFoundError(norm)
        data = self.files[norm]
        total = len(data)
        head_bytes = data[: max(0, head)]
        tail_bytes = data[-tail:] if tail > 0 and total > 0 else b""
        return head_bytes, tail_bytes, total

    def list_dir(self, path: str) -> list[str]:
        norm = _norm_posix(path)
        prefix = norm.rstrip("/") + "/"
        names: set[str] = set()
        for candidate in (*self.files.keys(), *self.devices.keys(), *self.dirs):
            if candidate != norm and candidate.startswith(prefix):
                rest = candidate[len(prefix):]
                if rest and "/" not in rest:
                    names.add(rest)
                elif "/" in rest:
                    names.add(rest.split("/", 1)[0])
        return sorted(names)

    def glob(self, pattern: str) -> list[str]:
        norm_pat = _norm_posix(pattern)
        candidates = sorted(set(self.files.keys()) | set(self.devices.keys()) | self.dirs)
        return [c for c in candidates if fnmatch.fnmatch(c, norm_pat)]

    def mem_total_mb(self) -> int | None:
        if self._mem_mb is not None:
            return self._mem_mb
        if "/proc/meminfo" in self.files:
            text = self.files["/proc/meminfo"].decode("utf-8", errors="replace")
            for line in text.splitlines():
                if line.startswith("MemTotal:"):
                    parts = line.split()
                    return int(parts[1]) // 1024
        return None

    def is_root(self) -> bool:
        return self._root


class FakeCgroupController:
    """In-memory cgroup v2 controller tracking freeze/thaw transitions."""

    def __init__(self, *, available: bool = True) -> None:
        self.available = available
        self.cgroups: set[str] = set()
        self.frozen_states: dict[str, bool] = {}
        self.memory_bytes: dict[str, int] = {}
        self.history: list[tuple[str, str]] = []

    def ensure_cgroup(self, name: str) -> str:
        if not self.available:
            raise OSError("cgroup v2 hierarchy unavailable")
        self.cgroups.add(name)
        self.frozen_states.setdefault(name, False)
        self.history.append(("ensure", name))
        return f"/sys/fs/cgroup/kitebridge/{name}"

    def freeze(self, name: str) -> None:
        if not self.available:
            raise OSError("cgroup.freeze unavailable")
        self.cgroups.add(name)
        self.frozen_states[name] = True
        self.history.append(("freeze", name))

    def thaw(self, name: str) -> None:
        if not self.available:
            raise OSError("cgroup.freeze unavailable")
        self.cgroups.add(name)
        self.frozen_states[name] = False
        self.history.append(("thaw", name))

    def is_frozen(self, name: str) -> bool:
        return bool(self.frozen_states.get(name, False))

    def read_memory_current(self, name: str) -> int | None:
        return self.memory_bytes.get(name)

    def destroy(self, name: str) -> None:
        self.cgroups.discard(name)
        self.frozen_states.pop(name, None)
        self.history.append(("destroy", name))


class TempDirCgroupController:
    """Tempdir-backed cgroup v2 double writing real `cgroup.freeze` files on Windows."""

    def __init__(self, base_dir: Path | str) -> None:
        self.base_dir = Path(base_dir)
        self.base_dir.mkdir(parents=True, exist_ok=True)
        self.history: list[tuple[str, str]] = []

    def _dir(self, name: str) -> Path:
        return self.base_dir / name

    def ensure_cgroup(self, name: str) -> str:
        d = self._dir(name)
        d.mkdir(parents=True, exist_ok=True)
        freeze_file = d / "cgroup.freeze"
        if not freeze_file.exists():
            freeze_file.write_text("0\n", encoding="utf-8")
        self.history.append(("ensure", name))
        return str(d)

    def freeze(self, name: str) -> None:
        self.ensure_cgroup(name)
        (self._dir(name) / "cgroup.freeze").write_text("1\n", encoding="utf-8")
        self.history.append(("freeze", name))

    def thaw(self, name: str) -> None:
        self.ensure_cgroup(name)
        (self._dir(name) / "cgroup.freeze").write_text("0\n", encoding="utf-8")
        self.history.append(("thaw", name))

    def is_frozen(self, name: str) -> bool:
        freeze_file = self._dir(name) / "cgroup.freeze"
        if not freeze_file.exists():
            return False
        return freeze_file.read_text(encoding="utf-8").strip() == "1"

    def read_memory_current(self, name: str) -> int | None:
        mem_file = self._dir(name) / "memory.current"
        if not mem_file.exists():
            return None
        return int(mem_file.read_text(encoding="utf-8").strip())

    def destroy(self, name: str) -> None:
        d = self._dir(name)
        if d.exists():
            shutil.rmtree(d)
        self.history.append(("destroy", name))


class InMemoryPrefixFilesystem:
    """Pure in-memory POSIX virtual filesystem with symlink tracking."""

    def __init__(self) -> None:
        self.dirs: set[str] = {"/"}
        self.files: dict[str, bytes] = {}
        self.symlinks: dict[str, str] = {}

    def _ensure_parents(self, norm: str) -> None:
        p = PurePosixPath(norm).parent
        while str(p) not in ("", "."):
            self.dirs.add(str(p))
            if str(p) == "/":
                break
            p = p.parent

    def exists(self, path: str) -> bool:
        norm = _norm_posix(path)
        return norm in self.files or norm in self.dirs or norm in self.symlinks

    def is_dir(self, path: str) -> bool:
        norm = _norm_posix(path)
        if norm in self.symlinks:
            target = _norm_posix(self.symlinks[norm])
            return target in self.dirs
        return norm in self.dirs

    def is_symlink(self, path: str) -> bool:
        return _norm_posix(path) in self.symlinks

    def mkdir(self, path: str, parents: bool = True) -> None:
        norm = _norm_posix(path)
        if parents:
            self._ensure_parents(norm)
        self.dirs.add(norm)

    def symlink(self, target: str, link_path: str) -> None:
        norm = _norm_posix(link_path)
        self._ensure_parents(norm)
        self.dirs.discard(norm)
        self.files.pop(norm, None)
        self.symlinks[norm] = _norm_posix(target)

    def readlink(self, path: str) -> str:
        norm = _norm_posix(path)
        if norm not in self.symlinks:
            raise OSError(f"Not a symlink: {norm}")
        return self.symlinks[norm]

    def read_text(self, path: str) -> str:
        return self.read_bytes(path).decode("utf-8")

    def write_text(self, path: str, data: str) -> None:
        self.write_bytes(path, data.encode("utf-8"))

    def read_bytes(self, path: str) -> bytes:
        norm = _norm_posix(path)
        if norm not in self.files:
            raise FileNotFoundError(norm)
        return self.files[norm]

    def file_size(self, path: str) -> int:
        norm = _norm_posix(path)
        if norm not in self.files:
            raise FileNotFoundError(norm)
        return len(self.files[norm])

    def read_head_tail(self, path: str, head: int = 4096, tail: int = 512) -> tuple[bytes, bytes, int]:
        data = self.read_bytes(path)
        total = len(data)
        head_bytes = data[: max(0, head)]
        tail_bytes = data[-tail:] if tail > 0 and total > 0 else b""
        return head_bytes, tail_bytes, total

    def write_bytes(self, path: str, data: bytes) -> None:
        norm = _norm_posix(path)
        self._ensure_parents(norm)
        self.files[norm] = data

    def glob(self, root: str, pattern: str) -> list[str]:
        norm_root = _norm_posix(root).rstrip("/")
        prefix = (norm_root + "/") if norm_root else "/"
        results: list[str] = []
        for candidate in sorted(set(self.files.keys()) | self.dirs | set(self.symlinks.keys())):
            if candidate.startswith(prefix):
                rel = candidate[len(prefix):]
                if (
                    fnmatch.fnmatch(rel, pattern)
                    or PurePosixPath(rel).match(pattern)
                    or (pattern.startswith("**/") and fnmatch.fnmatch(rel, pattern[3:]))
                ):
                    results.append(candidate)
        return results

    def list_dir(self, path: str) -> list[str]:
        norm = _norm_posix(path).rstrip("/")
        prefix = (norm + "/") if norm else "/"
        names: set[str] = set()
        for candidate in (*self.files.keys(), *self.dirs, *self.symlinks.keys()):
            if candidate.startswith(prefix):
                rest = candidate[len(prefix):]
                if rest:
                    names.add(rest.split("/", 1)[0])
        return sorted(names)

    def remove(self, path: str) -> None:
        norm = _norm_posix(path)
        self.files.pop(norm, None)
        self.symlinks.pop(norm, None)
        self.dirs.discard(norm)
        prefix = norm.rstrip("/") + "/"
        for key in list(self.files.keys()):
            if key.startswith(prefix):
                del self.files[key]
        for key in list(self.symlinks.keys()):
            if key.startswith(prefix):
                del self.symlinks[key]
        for d in list(self.dirs):
            if d.startswith(prefix):
                self.dirs.discard(d)

    def rename(self, src: str, dst: str) -> None:
        s = _norm_posix(src)
        d = _norm_posix(dst)
        self._ensure_parents(d)
        if s in self.files:
            self.files[d] = self.files.pop(s)
        elif s in self.symlinks:
            self.symlinks[d] = self.symlinks.pop(s)
        elif s in self.dirs:
            self.dirs.discard(s)
            self.dirs.add(d)
            s_pref = s.rstrip("/") + "/"
            d_pref = d.rstrip("/") + "/"
            for k in list(self.files.keys()):
                if k.startswith(s_pref):
                    self.files[d_pref + k[len(s_pref):]] = self.files.pop(k)
            for dir_path in list(self.dirs):
                if dir_path.startswith(s_pref):
                    self.dirs.discard(dir_path)
                    self.dirs.add(d_pref + dir_path[len(s_pref):])
        else:
            raise FileNotFoundError(s)


class TempPrefixFilesystem:
    """PrefixFilesystem mapping virtual POSIX roots safely under a pytest tmp_path."""

    def __init__(self, base_dir: Path | str) -> None:
        self.base_dir = Path(base_dir).resolve()
        self.base_dir.mkdir(parents=True, exist_ok=True)
        # Track virtual symlinks if OS lacks symlink privilege
        self._virtual_symlinks: dict[str, str] = {}

    def _map(self, path: str) -> Path:
        raw = path.replace("\\", "/")
        # If path is already inside base_dir, keep it
        try:
            candidate = Path(path)
            if candidate.is_absolute() and str(candidate.resolve()).startswith(str(self.base_dir)):
                return candidate
        except OSError:
            pass
        rel = raw.lstrip("/")
        if ":" in rel.split("/")[0]:
            rel = rel.split(":", 1)[1].lstrip("/")
        return self.base_dir / rel

    def exists(self, path: str) -> bool:
        norm = _norm_posix(path)
        return norm in self._virtual_symlinks or self._map(path).exists()

    def is_dir(self, path: str) -> bool:
        return self._map(path).is_dir()

    def is_symlink(self, path: str) -> bool:
        norm = _norm_posix(path)
        return norm in self._virtual_symlinks or self._map(path).is_symlink()

    def mkdir(self, path: str, parents: bool = True) -> None:
        self._map(path).mkdir(parents=parents, exist_ok=True)

    def symlink(self, target: str, link_path: str) -> None:
        mapped_link = self._map(link_path)
        mapped_link.parent.mkdir(parents=True, exist_ok=True)
        if mapped_link.is_symlink() or mapped_link.exists():
            if mapped_link.is_dir() and not mapped_link.is_symlink():
                shutil.rmtree(mapped_link)
            else:
                mapped_link.unlink()
        try:
            target_path = self._map(target)
            mapped_link.symlink_to(target_path, target_is_directory=target_path.is_dir())
        except OSError:
            # Windows without Developer Mode symlink privilege: store marker & track link
            self._virtual_symlinks[_norm_posix(link_path)] = _norm_posix(target)
            mapped_link.write_text(f"SYMLINK->{target}", encoding="utf-8")

    def readlink(self, path: str) -> str:
        norm = _norm_posix(path)
        if norm in self._virtual_symlinks:
            return self._virtual_symlinks[norm]
        raw = str(os.readlink(self._map(path)))
        cleaned = raw[4:] if raw.startswith("\\\\?\\") else raw
        try:
            rel = Path(cleaned).resolve().relative_to(self.base_dir)
            return "/" + rel.as_posix().lstrip("/")
        except ValueError:
            return cleaned.replace("\\", "/")

    def read_text(self, path: str) -> str:
        return self._map(path).read_text(encoding="utf-8")

    def write_text(self, path: str, data: str) -> None:
        p = self._map(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(data, encoding="utf-8")

    def read_bytes(self, path: str) -> bytes:
        return self._map(path).read_bytes()

    def file_size(self, path: str) -> int:
        return self._map(path).stat().st_size

    def read_head_tail(self, path: str, head: int = 4096, tail: int = 512) -> tuple[bytes, bytes, int]:
        p = self._map(path)
        with open(p, "rb") as fh:
            fh.seek(0, os.SEEK_END)
            total = fh.tell()
            fh.seek(0)
            head_bytes = fh.read(max(0, head))
            if tail <= 0 or total == 0:
                tail_bytes = b""
            elif total <= tail:
                fh.seek(0)
                tail_bytes = fh.read(total)
            else:
                fh.seek(total - tail)
                tail_bytes = fh.read(tail)
            return head_bytes, tail_bytes, total

    def write_bytes(self, path: str, data: bytes) -> None:
        p = self._map(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)

    def glob(self, root: str, pattern: str) -> list[str]:
        mapped = self._map(root)
        if not mapped.exists():
            return []
        root_norm = _norm_posix(root).rstrip("/")
        out: list[str] = []
        for match in sorted(mapped.glob(pattern)):
            rel = match.relative_to(mapped).as_posix()
            out.append(f"{root_norm}/{rel}")
        return out

    def list_dir(self, path: str) -> list[str]:
        mapped = self._map(path)
        if not mapped.exists():
            return []
        return sorted(item.name for item in mapped.iterdir())

    def remove(self, path: str) -> None:
        self._virtual_symlinks.pop(_norm_posix(path), None)
        p = self._map(path)
        if p.is_symlink() or p.is_file():
            p.unlink()
        elif p.is_dir():
            shutil.rmtree(p)

    def rename(self, src: str, dst: str) -> None:
        dst_p = self._map(dst)
        dst_p.parent.mkdir(parents=True, exist_ok=True)
        self._map(src).rename(dst_p)


class FakeMountManager:
    """In-memory MountManager double for router/CLI tests."""

    def __init__(self) -> None:
        self.mounts: dict[str, MountRecord] = {}
        self.operations: list[tuple[str, str, str]] = []

    def mount_dmg(self, image_path: str, mountpoint: str) -> MountRecord:
        rec = MountRecord(image_path, mountpoint, "dmg", read_only=True, fuse=True)
        self.mounts[mountpoint] = rec
        self.operations.append(("mount_dmg", image_path, mountpoint))
        return rec

    def mount_hfsplus(
        self,
        source_path: str,
        mountpoint: str,
        *,
        read_only: bool = True,
        fsck: bool = True,
    ) -> MountRecord:
        rec = MountRecord(source_path, mountpoint, "hfsplus", read_only=read_only, fuse=False)
        self.mounts[mountpoint] = rec
        self.operations.append(("mount_hfsplus", source_path, mountpoint))
        return rec

    def mount_apfs(
        self,
        source_path: str,
        mountpoint: str,
        *,
        read_only: bool = True,
    ) -> MountRecord:
        rec = MountRecord(source_path, mountpoint, "apfs", read_only=read_only, fuse=True)
        self.mounts[mountpoint] = rec
        self.operations.append(("mount_apfs", source_path, mountpoint))
        return rec

    def unmount(self, mountpoint: str) -> None:
        self.mounts.pop(mountpoint, None)
        self.operations.append(("unmount", mountpoint, ""))

    def is_mounted(self, mountpoint: str) -> bool:
        return mountpoint in self.mounts

    def list_mounts(self) -> list[MountRecord]:
        return list(self.mounts.values())


class FakeQmpClient:
    """In-memory QmpClient double supporting failure injection and snapshot tracking."""

    def __init__(
        self,
        *,
        initial_status: str = "running",
        snapshots: set[str] | None = None,
        fail_on: Mapping[str, str] | None = None,
    ) -> None:
        self.connected_socket: str | None = None
        self.status = initial_status
        self.snapshots: set[str] = set(snapshots or ())
        self.fail_on: dict[str, str] = dict(fail_on or {})
        self.commands: list[tuple[str, dict[str, Any]]] = []

    def _check_fail(self, cmd: str) -> None:
        if cmd in self.fail_on:
            raise QmpError(self.fail_on[cmd])

    def connect(self, socket_path: str) -> None:
        self._check_fail("connect")
        self.connected_socket = socket_path
        self.commands.append(("connect", {"socket_path": socket_path}))

    def capabilities(self) -> dict[str, Any]:
        self._check_fail("capabilities")
        self.commands.append(("qmp_capabilities", {}))
        return {"QMP": {"version": {"qemu": {"major": 9, "minor": 0}}}}

    def query_status(self) -> str:
        self._check_fail("query_status")
        self.commands.append(("query-status", {}))
        return self.status

    def savevm(self, tag: str = "kite-idle") -> None:
        self.commands.append(("savevm", {"tag": tag}))
        self._check_fail("savevm")
        self.snapshots.add(tag)

    def loadvm(self, tag: str = "kite-idle") -> None:
        self.commands.append(("loadvm", {"tag": tag}))
        self._check_fail("loadvm")
        if tag not in self.snapshots:
            raise QmpError(f"Snapshot '{tag}' not found")

    def stop(self) -> None:
        self._check_fail("stop")
        self.status = "paused"
        self.commands.append(("stop", {}))

    def cont(self) -> None:
        self._check_fail("cont")
        self.status = "running"
        self.commands.append(("cont", {}))

    def system_powerdown(self) -> None:
        self._check_fail("system_powerdown")
        self.status = "shutdown"
        self.commands.append(("system_powerdown", {}))

    def quit(self) -> None:
        self._check_fail("quit")
        self.status = "quit"
        self.commands.append(("quit", {}))

    def close(self) -> None:
        self.commands.append(("close", {}))
        self.connected_socket = None


class FakeHwProfileReader:
    """In-memory HwProfileReader returning a deterministic HwProfile."""

    def __init__(self, profile: HwProfile | None = None) -> None:
        self.profile = profile or HwProfile()

    def read(self, path: str | None = None) -> HwProfile:
        return self.profile
