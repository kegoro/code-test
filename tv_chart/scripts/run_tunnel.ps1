# Expose the local UDF server to the public internet via Cloudflare Tunnel.
#
# Prereq (one-time):
#   1. winget install --id Cloudflare.cloudflared
#      (or download cloudflared.exe from https://github.com/cloudflare/cloudflared/releases)
#   2. Make sure run_server.ps1 is running in another terminal first.
#
# This script uses the EPHEMERAL tunnel: every restart picks a fresh random
# *.trycloudflare.com hostname. For a stable URL, register a named tunnel
# (`cloudflared tunnel login` → `tunnel create` → DNS route) and replace the
# command below with `cloudflared tunnel run <name>`.

$ErrorActionPreference = 'Stop'

if (-not (Get-Command cloudflared -ErrorAction SilentlyContinue)) {
  Write-Host "cloudflared not found on PATH." -ForegroundColor Red
  Write-Host "Install with:  winget install --id Cloudflare.cloudflared"
  exit 1
}

Write-Host "Starting Cloudflare ephemeral tunnel → http://localhost:8080" -ForegroundColor Cyan
Write-Host "(Look for the trycloudflare.com URL in the output below; share that with your phone.)"
Write-Host ""

cloudflared tunnel --url http://localhost:8080
