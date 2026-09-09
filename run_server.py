"""Local dev entrypoint for the FastAPI backend + minimal web UI."""

from __future__ import annotations

import uvicorn

from backlot.config import get_settings


def main() -> None:
    settings = get_settings()
    uvicorn.run("backlot.api.app:app", host=settings.api_host, port=settings.api_port)


if __name__ == "__main__":
    main()
