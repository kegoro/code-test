$ErrorActionPreference = 'Stop'

$port = 8000

$pids = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue |
    Select-Object -ExpandProperty OwningProcess -Unique

foreach ($processId in $pids) {
    try {
        Stop-Process -Id $processId -Force -ErrorAction Stop
        Write-Host "Killed PID $processId on port $port"
    } catch {
        Write-Warning "Failed to kill PID $processId : $_"
    }
}

$repoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $repoRoot

uvicorn backend.main:app --port $port
