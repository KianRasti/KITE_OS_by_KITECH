"""QMP lifecycle manager for OSX-KVM hibernate (savevm/loadvm) and graceful shutdown."""

from __future__ import annotations

from ..abstractions import QmpClient, UnixSocketQmpClient
from ..models import QmpError


class QmpLifecycleManager:
    """Manages QEMU Monitor Protocol savevm/loadvm hibernate with vhost-user-fs fallback."""

    def __init__(self, client: QmpClient | None = None) -> None:
        self.client = client or UnixSocketQmpClient()

    def query_status(self, socket_path: str) -> str:
        self.client.connect(socket_path)
        try:
            self.client.capabilities()
            return self.client.query_status()
        finally:
            self.client.close()

    def hibernate(self, socket_path: str, *, tag: str = "kite-idle") -> tuple[bool, str | None]:
        """Pause, snapshot RAM/state via savevm, and quit QEMU; falls back cleanly on vhost-user-fs blocker."""
        self.client.connect(socket_path)
        saved = False
        fallback_note: str | None = None
        try:
            self.client.capabilities()
            self.client.stop()
            try:
                self.client.savevm(tag)
                saved = True
            except QmpError as exc:
                fallback_note = f"savevm failed ({exc}); falling back to clean powerdown/quit."
                try:
                    self.client.cont()
                    self.client.system_powerdown()
                except QmpError:
                    pass
            try:
                self.client.quit()
            except QmpError:
                pass
        finally:
            self.client.close()
        return saved, fallback_note

    def resume_via_qmp(self, socket_path: str, *, tag: str = "kite-idle") -> None:
        self.client.connect(socket_path)
        try:
            self.client.capabilities()
            self.client.loadvm(tag)
            self.client.cont()
        finally:
            self.client.close()
