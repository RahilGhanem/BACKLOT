"""Local dev entrypoint for the FastAPI backend + minimal web UI.

Usage:
    python run_server.py

Then open http://127.0.0.1:8000 (or your configured API_HOST/API_PORT).

The Budget/Resource agents still need the MCP server reachable — start it
separately, same as run_local.py:
    python -m backlot.mcp_shim.server
"""

from __future__ import annotations

import uvicorn

from backlot.config import get_settings


def main() -> None:
    settings = get_settings()
    uvicorn.run("backlot.api.app:app", host=settings.api_host, port=settings.api_port)


if __name__ == "__main__":
    main()
