"""Runtime-checkable OS abstraction Protocols and Linux production implementations.

All modules avoid top-level Unix-only imports (os.geteuid, pwd, grp, fcntl, socket.AF_UNIX)
so everything imports and unit-tests cleanly on Windows Python 3.12.
"""

from __future__ import annotations

import json
import os
import shutil
import socket
import stat
import subprocess
from pathlib import Path, PurePosixPath
from typing import Any, Mapping, Protocol, Sequence, runtime_checkable

from .models import CommandResult, HwProfile, QmpError

FORBIDDEN_DX_ENV_KEYS = (
    "VKD3D_CONFIG",
    "VKD3D_FEATURE_LEVEL",
    "VKD3D_SHADER_DEBUG",
    "PROTON_USE_VKD3D",
)


@runtime_checkable
class ProcessRunner(Protocol):
    def run(
        self,
        argv: Sequence[str],
        *,
        env: Mapping[str, str] | None = None,
        cwd: str | None = None,
        check: bool = False,
        timeout: float | None = None,
    ) -> CommandResult: ...

    def spawn(
        self,
        argv: Sequence[str],
        *,
        env: Mapping[str, str] | None = None,
        cwd: str | None = None,
    ) -> int: ...

    def which(self, binary: str) -> str | None: ...


@runtime_checkable
class SystemProbe(Protocol):
    def exists(self, path: str) -> bool: ...

    def is_char_device(self, path: str) -> bool: ...

    def is_dir(self, path: str) -> bool: ...

    def access_rw(self, path: str) -> bool: ...

    def read_text(self, path: str) -> str: ...

    def read_bytes(self, path: str, limit: int | None = None) -> bytes: ...

    def read_head_tail(self, path: str, head: int = 4096, tail: int = 512) -> tuple[bytes, bytes, int]: ...

    def list_dir(self, path: str) -> list[str]: ...

    def glob(self, pattern: str) -> list[str]: ...

    def mem_total_mb(self) -> int | None: ...

    def is_root(self) -> bool: ...


@runtime_checkable
class CgroupController(Protocol):
    def ensure_cgroup(self, name: str) -> str: ...

    def freeze(self, name: str) -> None: ...

    def thaw(self, name: str) -> None: ...

    def is_frozen(self, name: str) -> bool: ...

    def read_memory_current(self, name: str) -> int | None: ...

    def destroy(self, name: str) -> None: ...


@runtime_checkable
class PrefixFilesystem(Protocol):
    def exists(self, path: str) -> bool: ...

    def is_dir(self, path: str) -> bool: ...

    def is_symlink(self, path: str) -> bool: ...

    def mkdir(self, path: str, parents: bool = True) -> None: ...

    def symlink(self, target: str, link_path: str) -> None: ...

    def readlink(self, path: str) -> str: ...

    def read_text(self, path: str) -> str: ...

    def write_text(self, path: str, data: str) -> None: ...

    def read_bytes(self, path: str) -> bytes: ...

    def file_size(self, path: str) -> int: ...

    def read_head_tail(self, path: str, head: int = 4096, tail: int = 512) -> tuple[bytes, bytes, int]: ...

    def write_bytes(self, path: str, data: bytes) -> None: ...

    def glob(self, root: str, pattern: str) -> list[str]: ...

    def list_dir(self, path: str) -> list[str]: ...

    def remove(self, path: str) -> None: ...

    def rename(self, src: str, dst: str) -> None: ...


@runtime_checkable
class MountManager(Protocol):
    def mount_dmg(self, image_path: str, mountpoint: str) -> Any: ...

    def mount_hfsplus(
        self,
        source_path: str,
        mountpoint: str,
        *,
        read_only: bool = True,
        fsck: bool = True,
    ) -> Any: ...

    def mount_apfs(
        self,
        source_path: str,
        mountpoint: str,
        *,
        read_only: bool = True,
    ) -> Any: ...

    def unmount(self, mountpoint: str) -> None: ...

    def is_mounted(self, mountpoint: str) -> bool: ...

    def list_mounts(self) -> list[Any]: ...


@runtime_checkable
class QmpClient(Protocol):
    def connect(self, socket_path: str) -> None: ...

    def capabilities(self) -> dict[str, Any]: ...

    def query_status(self) -> str: ...

    def savevm(self, tag: str = "kite-idle") -> None: ...

    def loadvm(self, tag: str = "kite-idle") -> None: ...

    def stop(self) -> None: ...

    def cont(self) -> None: ...

    def system_powerdown(self) -> None: ...

    def quit(self) -> None: ...

    def close(self) -> None: ...


@runtime_checkable
class HwProfileReader(Protocol):
    def read(self, path: str | None = None) -> HwProfile: ...


class SubprocessRunner:
    """Production ProcessRunner backed by subprocess and shutil.which."""

    def run(
        self,
        argv: Sequence[str],
        *,
        env: Mapping[str, str] | None = None,
        cwd: str | None = None,
        check: bool = False,
        timeout: float | None = None,
    ) -> CommandResult:
        merged_env = os.environ.copy()
        if env:
            merged_env.update(env)
        for forbidden_key in FORBIDDEN_DX_ENV_KEYS:
            merged_env.pop(forbidden_key, None)
        proc = subprocess.run(
            list(argv),
            env=merged_env,
            cwd=cwd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            check=False,
        )
        res = CommandResult(
            argv=tuple(argv),
            returncode=proc.returncode,
            stdout=proc.stdout,
            stderr=proc.stderr,
        )
        if check and proc.returncode != 0:
            raise subprocess.CalledProcessError(
                proc.returncode,
                list(argv),
                output=proc.stdout,
                stderr=proc.stderr,
            )
        return res

    def spawn(
        self,
        argv: Sequence[str],
        *,
        env: Mapping[str, str] | None = None,
        cwd: str | None = None,
    ) -> int:
        merged_env = os.environ.copy()
        if env:
            merged_env.update(env)
        for forbidden_key in FORBIDDEN_DX_ENV_KEYS:
            merged_env.pop(forbidden_key, None)
        proc = subprocess.Popen(
            list(argv),
            env=merged_env,
            cwd=cwd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        return int(proc.pid)

    def which(self, binary: str) -> str | None:
        return shutil.which(binary)


class PosixSystemProbe:
    """Production SystemProbe safe to instantiate on any host OS."""

    @staticmethod
    def _virtual_dev_override(path: str) -> tuple[bool, bool] | None:
        norm = path.replace("\\", "/")
        dev_root = os.environ.get("KITE_DEV_ROOT")
        if norm == "/dev/kvm":
            flag = os.environ.get("KITE_DEV_KVM")
            if flag == "1":
                return True, True
            if flag == "0":
                return False, False
            if dev_root:
                p = Path(dev_root) / "kvm"
                return p.exists(), p.exists()
        elif norm == "/dev/ntsync":
            flag = os.environ.get("KITE_DEV_NTSYNC")
            if flag == "1":
                return True, True
            if flag == "0":
                return False, False
            if dev_root:
                p = Path(dev_root) / "ntsync"
                return p.exists(), p.exists()
        elif norm in ("/dev/binder", "/dev/binderfs/binder"):
            flag = os.environ.get("KITE_DEV_BINDER")
            if flag == "1":
                return True, True
            if flag == "0":
                return False, False
            if dev_root:
                p = Path(dev_root) / "binder"
                return p.exists(), p.exists()
        return None

    def exists(self, path: str) -> bool:
        override = self._virtual_dev_override(path)
        if override is not None:
            return override[0]
        return os.path.exists(path)

    def is_char_device(self, path: str) -> bool:
        override = self._virtual_dev_override(path)
        if override is not None:
            return override[0]
        try:
            st = os.stat(path)
            return stat.S_ISCHR(st.st_mode)
        except OSError:
            return False

    def is_dir(self, path: str) -> bool:
        return os.path.isdir(path)

    def access_rw(self, path: str) -> bool:
        override = self._virtual_dev_override(path)
        if override is not None:
            return override[1]
        return os.access(path, os.R_OK | os.W_OK)

    def read_text(self, path: str) -> str:
        return Path(path).read_text(encoding="utf-8")

    def read_bytes(self, path: str, limit: int | None = None) -> bytes:
        with open(path, "rb") as fh:
            if limit is None:
                return fh.read()
            return fh.read(limit)

    def read_head_tail(self, path: str, head: int = 4096, tail: int = 512) -> tuple[bytes, bytes, int]:
        with open(path, "rb") as fh:
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

    def list_dir(self, path: str) -> list[str]:
        return sorted(os.listdir(path))

    def glob(self, pattern: str) -> list[str]:
        norm = pattern.replace("\\", "/")
        if norm == "/dev/binder*":
            override = self._virtual_dev_override("/dev/binder")
            if override is not None:
                return ["/dev/binder"] if override[0] else []
        p = Path(pattern)
        parent = p.parent if str(p.parent) else Path(".")
        if not parent.exists():
            return []
        return sorted(str(item) for item in parent.glob(p.name))

    def mem_total_mb(self) -> int | None:
        meminfo = Path("/proc/meminfo")
        if not meminfo.exists():
            return None
        try:
            for line in meminfo.read_text(encoding="utf-8", errors="replace").splitlines():
                if line.startswith("MemTotal:"):
                    parts = line.split()
                    kb = int(parts[1])
                    return kb // 1024
        except (OSError, ValueError, IndexError):
            return None
        return None

    def is_root(self) -> bool:
        geteuid = getattr(os, "geteuid", None)
        if geteuid is None:
            return False
        return bool(geteuid() == 0)


class CgroupV2Controller:
    """Production cgroup v2 controller supporting Waydroid LXC or kitebridge slices."""

    DEFAULT_CANDIDATES = (
        "/sys/fs/cgroup/lxc.payload.waydroid",
        "/sys/fs/cgroup/system.slice/waydroid-container.service",
        "/sys/fs/cgroup/lxc/waydroid",
    )

    def __init__(self, root: str = "/sys/fs/cgroup/kitebridge") -> None:
        self.root = PurePosixPath(root)

    def _resolve_dir(self, name: str) -> Path:
        override = os.environ.get("KITEBRIDGE_WAYDROID_CGROUP")
        if override and name == "waydroid":
            return Path(override)
        if name == "waydroid":
            for candidate in self.DEFAULT_CANDIDATES:
                p = Path(candidate)
                if p.exists():
                    return p
        return Path(str(self.root / name))

    def ensure_cgroup(self, name: str) -> str:
        target = self._resolve_dir(name)
        target.mkdir(parents=True, exist_ok=True)
        return str(target)

    def freeze(self, name: str) -> None:
        target = self._resolve_dir(name)
        freeze_file = target / "cgroup.freeze"
        freeze_file.write_text("1\n", encoding="utf-8")

    def thaw(self, name: str) -> None:
        target = self._resolve_dir(name)
        freeze_file = target / "cgroup.freeze"
        freeze_file.write_text("0\n", encoding="utf-8")

    def is_frozen(self, name: str) -> bool:
        target = self._resolve_dir(name)
        freeze_file = target / "cgroup.freeze"
        if not freeze_file.exists():
            return False
        return freeze_file.read_text(encoding="utf-8").strip() == "1"

    def read_memory_current(self, name: str) -> int | None:
        target = self._resolve_dir(name)
        mem_file = target / "memory.current"
        if not mem_file.exists():
            return None
        try:
            return int(mem_file.read_text(encoding="utf-8").strip())
        except ValueError:
            return None

    def destroy(self, name: str) -> None:
        target = self._resolve_dir(name)
        if target.exists():
            target.rmdir()


class LocalPrefixFilesystem:
    """Production PrefixFilesystem backed by pathlib.Path."""

    def exists(self, path: str) -> bool:
        return Path(path).exists()

    def is_dir(self, path: str) -> bool:
        return Path(path).is_dir()

    def is_symlink(self, path: str) -> bool:
        return Path(path).is_symlink()

    def mkdir(self, path: str, parents: bool = True) -> None:
        Path(path).mkdir(parents=parents, exist_ok=True)

    def symlink(self, target: str, link_path: str) -> None:
        link = Path(link_path)
        link.parent.mkdir(parents=True, exist_ok=True)
        if link.is_symlink() or link.exists():
            link.unlink()
        link.symlink_to(target)

    def readlink(self, path: str) -> str:
        return str(os.readlink(path))

    def read_text(self, path: str) -> str:
        return Path(path).read_text(encoding="utf-8")

    def write_text(self, path: str, data: str) -> None:
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(data, encoding="utf-8")

    def read_bytes(self, path: str) -> bytes:
        return Path(path).read_bytes()

    def file_size(self, path: str) -> int:
        return Path(path).stat().st_size

    def read_head_tail(self, path: str, head: int = 4096, tail: int = 512) -> tuple[bytes, bytes, int]:
        with open(path, "rb") as fh:
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
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)

    def glob(self, root: str, pattern: str) -> list[str]:
        base = Path(root)
        if not base.exists():
            return []
        return sorted(str(item) for item in base.glob(pattern))

    def list_dir(self, path: str) -> list[str]:
        base = Path(path)
        if not base.exists():
            return []
        return sorted(item.name for item in base.iterdir())

    def remove(self, path: str) -> None:
        p = Path(path)
        if p.is_symlink() or p.is_file():
            p.unlink()
        elif p.is_dir():
            shutil.rmtree(p)

    def rename(self, src: str, dst: str) -> None:
        Path(src).rename(Path(dst))


class UnixSocketQmpClient:
    """QMP client communicating over UNIX domain sockets (guarded for Windows safety)."""

    def __init__(self, timeout: float = 5.0) -> None:
        self.timeout = timeout
        self._sock: socket.socket | None = None
        self._buf = b""

    def connect(self, socket_path: str) -> None:
        af_unix = getattr(socket, "AF_UNIX", None)
        if af_unix is None:
            raise QmpError("UNIX domain sockets are unavailable on this platform.")
        sock = socket.socket(af_unix, socket.SOCK_STREAM)
        sock.settimeout(self.timeout)
        try:
            sock.connect(socket_path)
            self._sock = sock
            # Consume greeting banner
            self._read_message()
        except OSError as exc:
            sock.close()
            raise QmpError(f"Failed to connect to QMP socket '{socket_path}': {exc}") from exc

    def _read_message(self) -> dict[str, Any]:
        assert self._sock is not None
        while b"\n" not in self._buf:
            chunk = self._sock.recv(4096)
            if not chunk:
                raise QmpError("QMP socket closed unexpectedly.")
            self._buf += chunk
        line, self._buf = self._buf.split(b"\n", 1)
        return json.loads(line.decode("utf-8"))

    def _execute(self, command: str, arguments: dict[str, Any] | None = None) -> Any:
        if self._sock is None:
            raise QmpError("QMP client is not connected.")
        payload: dict[str, Any] = {"execute": command}
        if arguments:
            payload["arguments"] = arguments
        self._sock.sendall((json.dumps(payload) + "\n").encode("utf-8"))
        while True:
            msg = self._read_message()
            if "event" in msg:
                continue
            if "error" in msg:
                raise QmpError(f"QMP command '{command}' failed: {msg['error']}")
            if "return" in msg:
                return msg["return"]

    def capabilities(self) -> dict[str, Any]:
        return dict(self._execute("qmp_capabilities") or {})

    def query_status(self) -> str:
        res = self._execute("query-status")
        return str(res.get("status", "unknown"))

    def savevm(self, tag: str = "kite-idle") -> None:
        self._execute("human-monitor-command", {"command-line": f"savevm {tag}"})

    def loadvm(self, tag: str = "kite-idle") -> None:
        self._execute("human-monitor-command", {"command-line": f"loadvm {tag}"})

    def stop(self) -> None:
        self._execute("stop")

    def cont(self) -> None:
        self._execute("cont")

    def system_powerdown(self) -> None:
        self._execute("system_powerdown")

    def quit(self) -> None:
        self._execute("quit")

    def close(self) -> None:
        if self._sock is not None:
            try:
                self._sock.close()
            finally:
                self._sock = None
