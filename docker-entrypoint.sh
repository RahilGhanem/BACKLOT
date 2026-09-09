#!/bin/sh
# Starts the web app, plus the local MCP server when MCP_MODE=shim.
#
# In shim mode the app and the MCP server share one container and talk over
# loopback. PORT is unset for the shim because config.py prefers PORT over
# MCP_SHIM_PORT (so the shim can be hosted standalone), which would
# otherwise make it bind the same port as the web app.
set -e

: "${PORT:=8080}"

if [ "${MCP_MODE:-shim}" = "shim" ]; then
  : "${MCP_SHIM_PORT:=8765}"
  echo "starting mcp_shim on 127.0.0.1:${MCP_SHIM_PORT}"
  env -u PORT MCP_SHIM_HOST=127.0.0.1 MCP_SHIM_PORT="${MCP_SHIM_PORT}" \
    python -m backlot.mcp_shim.server &

  # Wait for it to accept connections before the API starts serving.
  i=0
  while [ "$i" -lt 40 ]; do
    if python -c "import socket,sys; s=socket.socket(); s.settimeout(1); sys.exit(0 if s.connect_ex(('127.0.0.1',${MCP_SHIM_PORT}))==0 else 1)"; then
      echo "mcp_shim is up"
      break
    fi
    i=$((i + 1))
    sleep 0.5
  done
fi

exec uvicorn backlot.api.app:app --host 0.0.0.0 --port "${PORT}"
