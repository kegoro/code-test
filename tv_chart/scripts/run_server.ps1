# Launch the FastAPI UDF backend on port 8080.
# Usage:  .\tv_chart\scripts\run_server.ps1
$ErrorActionPreference = 'Stop'
$ProjectRoot = Split-Path $PSScriptRoot -Parent | Split-Path -Parent
Set-Location $ProjectRoot
$env:PYTHONPATH = $ProjectRoot
python -m uvicorn tv_chart.backend.main:app --host 0.0.0.0 --port 8080 --reload
