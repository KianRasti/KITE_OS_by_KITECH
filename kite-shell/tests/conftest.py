"""Pytest fixtures for kite-shell tests (Windows host and Linux CI compatible)."""

from __future__ import annotations

import functools
import http.server
import sys
import threading
from pathlib import Path
from typing import Iterator

import pytest

KITE_SHELL_DIR = Path(__file__).resolve().parents[1]
SETTINGS_PKG_ROOT = KITE_SHELL_DIR / "settings"

if str(SETTINGS_PKG_ROOT) not in sys.path:
    sys.path.insert(0, str(SETTINGS_PKG_ROOT))


@pytest.fixture(scope="session")
def kite_shell_dir() -> Path:
    return KITE_SHELL_DIR


@pytest.fixture(scope="session")
def preview_server_url() -> Iterator[str]:
    preview_dir = KITE_SHELL_DIR / "preview"
    handler = functools.partial(
        http.server.SimpleHTTPRequestHandler,
        directory=str(preview_dir),
    )

    class QuietHandler(http.server.SimpleHTTPRequestHandler):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, directory=str(preview_dir), **kwargs)

        def log_message(self, format: str, *args) -> None:  # noqa: A002
            return

    del handler
    httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), QuietHandler)
    port = httpd.server_address[1]
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{port}/"
    finally:
        httpd.shutdown()
        httpd.server_close()
