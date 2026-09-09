"""Shared MCP connection wiring for grounded agents (Budget, Resource)."""

from __future__ import annotations

import socket
from urllib.parse import urlparse

from google.adk.tools.mcp_tool.mcp_session_manager import StreamableHTTPConnectionParams
from google.adk.tools.mcp_tool.mcp_toolset import McpToolset

from ..config import Settings


def build_mcp_toolset(settings: Settings, tool_filter: list[str]) -> McpToolset:
    headers = (
        {"Authorization": f"Bearer {settings.mcp_auth_token}"}
        if settings.mcp_auth_token
        else None
    )
    return McpToolset(
        connection_params=StreamableHTTPConnectionParams(
            url=settings.mcp_server_url,
            headers=headers,
        ),
        tool_filter=tool_filter,
    )


def check_mcp_reachable(settings: Settings, timeout: float = 3.0) -> None:
    """Preflight check: fail fast with a clear, mode-aware error before the
    Line Producer gets deep into a run, rather than letting the first
    Budget/Resource tool call surface an opaque connection error."""
    settings.require_mcp_credentials()

    parsed = urlparse(settings.mcp_server_url)
    host = parsed.hostname
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    endpoint_label = f"clickhouse ({settings.mcp_server_url})" if settings.mcp_mode == "clickhouse" else f"mcp_shim ({settings.mcp_server_url})"

    if not host:
        raise RuntimeError(
            f"MCP_MODE={settings.mcp_mode}: mcp_server_url {settings.mcp_server_url!r} "
            "is not a valid URL."
        )

    try:
        with socket.create_connection((host, port), timeout=timeout):
            return
    except OSError as exc:
        hint = (
            "start it with `python -m backlot.mcp_shim.server`"
            if settings.mcp_mode == "shim"
            else (
                "verify the mcp-clickhouse server is running (e.g. `uvx "
                "--from mcp-clickhouse mcp-clickhouse` with its own "
                "CLICKHOUSE_HOST/PORT/USER/PASSWORD env vars set), that it's "
                "reachable at CLICKHOUSE_MCP_URL from here, and that your "
                "ClickHouse Cloud cluster itself is running"
            )
        )
        raise RuntimeError(
            f"MCP server unreachable — {endpoint_label}: {exc}. {hint}."
        ) from exc
