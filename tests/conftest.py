"""Shared pytest fixtures.

`mcp_shim_process` auto-starts the local synthetic MCP server for tests
that need it (Budget/Resource/full-pipeline live tests), so contributors
don't have to remember to launch it in a second terminal. If something is
already listening on the configured host/port (e.g. a developer started it
manually), the fixture leaves it alone and does not manage its lifecycle.
"""

from __future__ import annotations

import socket
import subprocess
import sys
import time
from urllib.parse import urlparse

import pytest

from backlot.config import REPO_ROOT, get_settings


def _is_listening(host: str, port: int) -> bool:
    try:
        with socket.create_connection((host, port), timeout=0.5):
            return True
    except OSError:
        return False


@pytest.fixture(scope="session")
def mcp_shim_process():
    settings = get_settings()
    parsed = urlparse(settings.mcp_server_url)
    host, port = parsed.hostname or "127.0.0.1", parsed.port or 8765

    if _is_listening(host, port):
        yield  # already running (started manually, or by an earlier test session)
        return

    proc = subprocess.Popen(
        [sys.executable, "-m", "backlot.mcp_shim.server"],
        cwd=str(REPO_ROOT),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        deadline = time.monotonic() + 10.0
        while time.monotonic() < deadline:
            if _is_listening(host, port):
                break
            if proc.poll() is not None:
                raise RuntimeError(
                    "mcp_shim server process exited before becoming reachable."
                )
            time.sleep(0.2)
        else:
            raise RuntimeError(
                f"mcp_shim server did not start listening on {host}:{port} in time."
            )
        yield
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
