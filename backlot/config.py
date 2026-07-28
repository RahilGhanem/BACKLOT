"""Central place every module reads configuration from.

Nothing in this codebase should call `os.getenv` directly outside this file —
that keeps the "no hardcoded secrets, everything from env/Secret Manager"
constraint checkable in one spot.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = REPO_ROOT / "data"
OUTPUT_DIR = REPO_ROOT / "output"

# Load .env once, on import. Real deployments (Agent Engine / Cloud Run) set
# these as actual environment variables / Secret Manager references instead,
# and load_dotenv() is a no-op if no .env file is present.
load_dotenv(REPO_ROOT / ".env")


def _bool_env(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    # Model routing
    gemini_model_flash: str
    gemini_model_pro: str

    # Auth
    use_vertexai: bool
    google_api_key: str
    google_cloud_project: str
    google_cloud_location: str

    # App identity
    app_name: str

    # MCP (Phase 3+)
    mcp_server_url: str
    mcp_auth_token: str

    # Cloud resources (Phase 7)
    gcs_bucket: str
    firestore_project: str

    log_level: str

    # Local API server (Phase 5)
    api_host: str
    api_port: int

    def require_llm_credentials(self) -> None:
        """Raise a clear, actionable error if Gemini auth isn't configured.

        Schema-only code paths (schema validation, the MCP shim, the
        scheduler solver) never need this; only code that actually calls a
        model does.
        """
        if self.use_vertexai:
            if not self.google_cloud_project:
                raise RuntimeError(
                    "GOOGLE_GENAI_USE_VERTEXAI=TRUE requires "
                    "GOOGLE_CLOUD_PROJECT to be set in .env."
                )
        elif not self.google_api_key:
            raise RuntimeError(
                "No Gemini credentials configured. Copy .env.example to "
                ".env and set GOOGLE_API_KEY (AI Studio) or set "
                "GOOGLE_GENAI_USE_VERTEXAI=TRUE plus GOOGLE_CLOUD_PROJECT "
                "(Vertex AI)."
            )


def get_settings() -> Settings:
    return Settings(
        gemini_model_flash=os.getenv("GEMINI_MODEL_FLASH", "gemini-3-flash"),
        gemini_model_pro=os.getenv("GEMINI_MODEL_PRO", "gemini-3.1-pro"),
        use_vertexai=_bool_env("GOOGLE_GENAI_USE_VERTEXAI", default=False),
        google_api_key=os.getenv("GOOGLE_API_KEY", ""),
        google_cloud_project=os.getenv("GOOGLE_CLOUD_PROJECT", ""),
        google_cloud_location=os.getenv("GOOGLE_CLOUD_LOCATION", "us-central1"),
        app_name=os.getenv("BACKLOT_APP_NAME", "backlot"),
        mcp_server_url=os.getenv("MCP_SERVER_URL", "http://127.0.0.1:8765/mcp"),
        mcp_auth_token=os.getenv("MCP_AUTH_TOKEN", ""),
        gcs_bucket=os.getenv("GCS_BUCKET", ""),
        firestore_project=os.getenv("FIRESTORE_PROJECT", ""),
        log_level=os.getenv("LOG_LEVEL", "INFO"),
        api_host=os.getenv("API_HOST", "127.0.0.1"),
        api_port=int(os.getenv("API_PORT", "8000")),
    )
