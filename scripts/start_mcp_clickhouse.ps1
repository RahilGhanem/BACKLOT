# Starts the official mcp-clickhouse server from its own venv, using the
# CLICKHOUSE_* values in .env. A separate venv is required: mcp-clickhouse
# needs mcp>=2.x and this app pins mcp 1.29.0 for google-adk.
#
# Usage: .\scripts\start_mcp_clickhouse.ps1   (Ctrl+C to stop)

$ErrorActionPreference = "Stop"
$repo = Split-Path -Parent $PSScriptRoot
$venv = Join-Path $repo ".mcp-clickhouse-venv\Scripts\mcp-clickhouse.exe"
$envFile = Join-Path $repo ".env"

if (-not (Test-Path $venv)) {
    Write-Error "Missing $venv`nCreate it with:`n  python -m venv .mcp-clickhouse-venv`n  .mcp-clickhouse-venv\Scripts\python.exe -m pip install mcp-clickhouse==0.6.0"
}
if (-not (Test-Path $envFile)) { Write-Error "Missing .env (copy .env.example and fill it in)" }

# Load only the CLICKHOUSE_* vars this server needs. Nothing is printed --
# CLICKHOUSE_PASSWORD must never reach the console or a log.
$loaded = @()
foreach ($line in Get-Content $envFile) {
    if ($line -match '^\s*#') { continue }
    if ($line -notmatch '^\s*(CLICKHOUSE_[A-Z_]+)\s*=\s*(.*)$') { continue }
    $name = $Matches[1]
    $value = $Matches[2].Trim().Trim('"').Trim("'")
    if ([string]::IsNullOrWhiteSpace($value)) { continue }
    # CLICKHOUSE_MCP_URL is the CLIENT's address for this server, not a
    # server setting -- passing it through would confuse mcp-clickhouse.
    if ($name -eq "CLICKHOUSE_MCP_URL") { continue }
    Set-Item -Path "Env:$name" -Value $value
    $loaded += $name
}

Write-Host "Loaded from .env: $($loaded -join ', ')"
Write-Host "Serving MCP on http://$($env:CLICKHOUSE_MCP_BIND_HOST):$($env:CLICKHOUSE_MCP_BIND_PORT)/mcp"
Write-Host "ClickHouse target: $($env:CLICKHOUSE_HOST):$($env:CLICKHOUSE_PORT) db=$($env:CLICKHOUSE_DATABASE)"
Write-Host "Ctrl+C to stop.`n"

& $venv
