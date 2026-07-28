"""Shared MCP connection wiring for grounded agents (Budget, Resource).

Pointing this at the real IBM watsonx.data remote MCP server instead of the
local mcp_shim is an env change only (MCP_SERVER_URL, MCP_AUTH_TOKEN) — see
.env.example.
"""

from __future__ import annotations

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
