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


def _enterprise_mode_enabled() -> bool:
    """Whether Gemini calls should route through Vertex AI / the Gemini
    Enterprise Agent Platform rather than the AI Studio Developer API.

    Mirrors google.adk.utils.env_utils.is_enterprise_mode_enabled()'s own
    precedence exactly: GOOGLE_GENAI_USE_ENTERPRISE wins if set; otherwise
    fall back to the older GOOGLE_GENAI_USE_VERTEXAI. ADK's internals read
    the same two variables independently (they resolve the model for every
    LlmAgent call), so this file's precedence has to match ADK's or the two
    could disagree about which mode is active. We don't re-emit ADK's
    DeprecationWarning here — ADK's own call site already does, once.
    """
    if "GOOGLE_GENAI_USE_ENTERPRISE" in os.environ:
        return _bool_env("GOOGLE_GENAI_USE_ENTERPRISE")
    return _bool_env("GOOGLE_GENAI_USE_VERTEXAI", default=False)


@dataclass(frozen=True)
class Settings:
    # Model routing
    gemini_model_flash: str
    gemini_model_pro: str
    imagen_model: str
    veo_model: str
    lyria_model: str

    # Auth
    use_vertexai: bool
    google_api_key: str
    google_cloud_project: str
    google_cloud_location: str

    # App identity
    app_name: str

    # MCP (Phase 3+): mcp_server_url is what CLIENTS (Budget/Resource
    # agents) connect to; mcp_shim_host/port is what the shim server
    # itself binds to. Locally these describe the same address, but in a
    # cloud deployment the shim binds 0.0.0.0:$PORT internally while
    # clients reach it via its public HTTPS URL — two different strings.
    mcp_server_url: str
    mcp_auth_token: str
    mcp_shim_host: str
    mcp_shim_port: int

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
                    "GOOGLE_GENAI_USE_ENTERPRISE=TRUE (or the older "
                    "GOOGLE_GENAI_USE_VERTEXAI=TRUE) requires "
                    "GOOGLE_CLOUD_PROJECT to be set in .env."
                )
        elif not self.google_api_key:
            raise RuntimeError(
                "No Gemini credentials configured. Copy .env.example to "
                ".env and set GOOGLE_API_KEY (AI Studio) or set "
                "GOOGLE_GENAI_USE_ENTERPRISE=TRUE plus GOOGLE_CLOUD_PROJECT "
                "(Vertex AI)."
            )


def get_settings() -> Settings:
    return Settings(
        gemini_model_flash=os.getenv("GEMINI_MODEL_FLASH", "gemini-3.6-flash"),
        gemini_model_pro=os.getenv("GEMINI_MODEL_PRO", "gemini-3.6-flash"),
        imagen_model=os.getenv("IMAGEN_MODEL", "imagen-4.0-generate-001"),
        veo_model=os.getenv("VEO_MODEL", "veo-3.1-generate-preview"),
        lyria_model=os.getenv("LYRIA_MODEL", "lyria-3-clip-preview"),
        use_vertexai=_enterprise_mode_enabled(),
        google_api_key=os.getenv("GOOGLE_API_KEY", ""),
        google_cloud_project=os.getenv("GOOGLE_CLOUD_PROJECT", ""),
        google_cloud_location=os.getenv("GOOGLE_CLOUD_LOCATION", "us-central1"),
        app_name=os.getenv("BACKLOT_APP_NAME", "backlot"),
        mcp_server_url=os.getenv("MCP_SERVER_URL", "http://127.0.0.1:8765/mcp"),
        mcp_auth_token=os.getenv("MCP_AUTH_TOKEN", ""),
        mcp_shim_host=os.getenv("MCP_SHIM_HOST", "127.0.0.1"),
        mcp_shim_port=int(os.getenv("PORT", os.getenv("MCP_SHIM_PORT", "8765"))),
        gcs_bucket=os.getenv("GCS_BUCKET", ""),
        firestore_project=os.getenv("FIRESTORE_PROJECT", ""),
        log_level=os.getenv("LOG_LEVEL", "INFO"),
        api_host=os.getenv("API_HOST", "127.0.0.1"),
        # Cloud Run injects PORT and requires the container to listen on
        # it; PORT (if set) wins over API_PORT so the same image works
        # both locally (API_PORT) and on Cloud Run (PORT), unchanged.
        api_port=int(os.getenv("PORT", os.getenv("API_PORT", "8000"))),
    )
