"""Config precedence tests — no network.

get_settings() reads os.environ fresh on every call (no caching), so these
just monkeypatch the environment directly rather than reloading the module.
"""

from backlot.config import get_settings


def test_port_env_var_wins_over_api_port(monkeypatch):
    monkeypatch.setenv("PORT", "8080")
    monkeypatch.setenv("API_PORT", "9000")
    assert get_settings().api_port == 8080


def test_api_port_used_when_port_unset(monkeypatch):
    monkeypatch.delenv("PORT", raising=False)
    monkeypatch.setenv("API_PORT", "9000")
    assert get_settings().api_port == 9000


def test_api_port_defaults_to_8000(monkeypatch):
    monkeypatch.delenv("PORT", raising=False)
    monkeypatch.delenv("API_PORT", raising=False)
    assert get_settings().api_port == 8000


def test_port_env_var_wins_over_mcp_shim_port(monkeypatch):
    monkeypatch.setenv("PORT", "8080")
    monkeypatch.setenv("MCP_SHIM_PORT", "9000")
    assert get_settings().mcp_shim_port == 8080


def test_mcp_shim_port_defaults_to_8765(monkeypatch):
    monkeypatch.delenv("PORT", raising=False)
    monkeypatch.delenv("MCP_SHIM_PORT", raising=False)
    assert get_settings().mcp_shim_port == 8765


def test_mcp_shim_host_and_server_url_are_independent_settings(monkeypatch):
    monkeypatch.setenv("MCP_SHIM_HOST", "0.0.0.0")
    monkeypatch.setenv("MCP_SERVER_URL", "https://mcp-shim-xyz.a.run.app/mcp")
    settings = get_settings()
    assert settings.mcp_shim_host == "0.0.0.0"
    assert settings.mcp_server_url == "https://mcp-shim-xyz.a.run.app/mcp"
