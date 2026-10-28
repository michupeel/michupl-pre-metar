param([ValidateRange(1024,65535)][int]$Port = 8765)
$ErrorActionPreference = 'Stop'
$dashboardRoot = Split-Path -Parent $PSScriptRoot
Push-Location -LiteralPath $dashboardRoot
try {
    uv run premetar dashboard --port $Port
} finally {
    Pop-Location
}
