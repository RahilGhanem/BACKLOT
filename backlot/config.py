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


def _resolve_mcp_mode() -> str:
    """'shim' (default) talks to the local synthetic mcp_shim server;
    'clickhouse' points the Budget/Resource agents at the real, official
    ClickHouse MCP server (github.com/ClickHouse/mcp-clickhouse) connected to
    a ClickHouse Cloud or self-hosted cluster instead — see
    budget.py/resource.py's per-mode instructions and .env.example's
    ClickHouse section."""
    mode = os.getenv("MCP_MODE", "shim").strip().lower()
    if mode not in {"shim", "clickhouse"}:
        raise RuntimeError(f"MCP_MODE must be 'shim' or 'clickhouse' (got {mode!r}).")
    return mode


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
    #
    # mcp_mode picks which endpoint mcp_server_url/mcp_auth_token resolve
    # from (see _resolve_mcp_mode() below): 'shim' reads MCP_SERVER_URL /
    # MCP_AUTH_TOKEN (the local synthetic server); 'clickhouse' reads
    # CLICKHOUSE_MCP_URL / CLICKHOUSE_MCP_AUTH_TOKEN (the real, official
    # ClickHouse MCP server, github.com/ClickHouse/mcp-clickhouse) instead.
    # clickhouse_database is the database name the Budget/Resource agents
    # pass to that server's list_tables/run_query tools — unused in shim
    # mode. Note there's no per-client "engine id" concept here (unlike a
    # Presto-style lakehouse): mcp-clickhouse's own CLICKHOUSE_HOST/PORT/
    # USER/PASSWORD env vars (set on whoever runs that server, never here)
    # already pin it to one cluster.
    mcp_mode: str
    mcp_server_url: str
    mcp_auth_token: str
    mcp_shim_host: str
    mcp_shim_port: int
    clickhouse_database: str

    # Cloud resources (Phase 7)
    gcs_bucket: str
    firestore_project: str

    log_level: str

    # Local API server (Phase 5)
    api_host: str
    api_port: int

    # Safety cap on total Gemini calls per crew run (ADK's RunConfig.
    # max_llm_calls, default 500 is far too loose for a free-tier account
    # with e.g. a 20-requests/day cap) — protects against a runaway
    # tool-calling loop burning through a whole day's quota in one run.
    max_llm_calls_per_run: int

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

    def require_mcp_credentials(self) -> None:
        """Raise a clear, actionable error if clickhouse mode is missing any
        of the coordinates its tool calls need. No-op in shim mode —
        MCP_SERVER_URL always has a usable local default (see get_settings).
        """
        if self.mcp_mode != "clickhouse":
            return
        missing = [
            env_name
            for env_name, value in (
                ("CLICKHOUSE_MCP_URL", self.mcp_server_url),
                ("CLICKHOUSE_DATABASE", self.clickhouse_database),
            )
            if not value
        ]
        if missing:
            raise RuntimeError(
                "MCP_MODE=clickhouse requires " + ", ".join(missing) + " to be "
                "set in .env — see .env.example's ClickHouse section. "
                "(CLICKHOUSE_MCP_AUTH_TOKEN is also usually required by the "
                "MCP server but isn't validated here, since some deployments "
                "run it with auth disabled.)"
            )


def get_settings() -> Settings:
    mcp_mode = _resolve_mcp_mode()
    if mcp_mode == "clickhouse":
        mcp_server_url = os.getenv("CLICKHOUSE_MCP_URL", "")
        mcp_auth_token = os.getenv("CLICKHOUSE_MCP_AUTH_TOKEN", "")
    else:
        mcp_server_url = os.getenv("MCP_SERVER_URL", "http://127.0.0.1:8765/mcp")
        mcp_auth_token = os.getenv("MCP_AUTH_TOKEN", "")

    return Settings(
        gemini_model_flash=os.getenv("GEMINI_MODEL_FLASH", "gemini-3.6-flash"),
        gemini_model_pro=os.getenv("GEMINI_MODEL_PRO", "gemini-3.6-flash"),
        # gemini-2.5-flash-image ("Nano Banana") replaces the old default,
        # imagen-4.0-generate-001 -- every Imagen 4 generate-family id has a
        # "Discontinuation date: June 30, 2026" per Google Cloud's own
        # Vertex AI docs, already past. This is a real, current model id
        # (verified in the installed google-genai SDK's own Model type),
        # but note it's called through a different code path than a plain
        # Imagen id would be -- see backlot/tools/previz_generation.py's
        # generate_storyboards() docstring.
        imagen_model=os.getenv("IMAGEN_MODEL", "gemini-2.5-flash-image"),
        # veo-3.1-generate-001 is the current GA id (the old default,
        # veo-3.1-generate-preview, was a preview endpoint deprecated with a
        # migration deadline of April 2, 2026 -- already past). Verified
        # against Google Cloud's Vertex AI release notes.
        veo_model=os.getenv("VEO_MODEL", "veo-3.1-generate-001"),
        lyria_model=os.getenv("LYRIA_MODEL", "lyria-3-clip-preview"),
        use_vertexai=_enterprise_mode_enabled(),
        google_api_key=os.getenv("GOOGLE_API_KEY", ""),
        google_cloud_project=os.getenv("GOOGLE_CLOUD_PROJECT", ""),
        google_cloud_location=os.getenv("GOOGLE_CLOUD_LOCATION", "us-central1"),
        app_name=os.getenv("BACKLOT_APP_NAME", "backlot"),
        mcp_mode=mcp_mode,
        mcp_server_url=mcp_server_url,
        mcp_auth_token=mcp_auth_token,
        mcp_shim_host=os.getenv("MCP_SHIM_HOST", "127.0.0.1"),
        mcp_shim_port=int(os.getenv("PORT", os.getenv("MCP_SHIM_PORT", "8765"))),
        clickhouse_database=os.getenv("CLICKHOUSE_DATABASE", "backlot_studio"),
        gcs_bucket=os.getenv("GCS_BUCKET", ""),
        firestore_project=os.getenv("FIRESTORE_PROJECT", ""),
        log_level=os.getenv("LOG_LEVEL", "INFO"),
        api_host=os.getenv("API_HOST", "127.0.0.1"),
        # Cloud Run injects PORT and requires the container to listen on
        # it; PORT (if set) wins over API_PORT so the same image works
        # both locally (API_PORT) and on Cloud Run (PORT), unchanged.
        api_port=int(os.getenv("PORT", os.getenv("API_PORT", "8000"))),
        max_llm_calls_per_run=int(os.getenv("MAX_LLM_CALLS_PER_RUN", "15")),
    )
