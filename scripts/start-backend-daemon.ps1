$ErrorActionPreference = 'Stop'

$port = 8000
$repoRoot = Split-Path -Parent $PSScriptRoot

# Kill any existing listener on the port
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

$logDir = Join-Path $repoRoot 'logs'
if (-not (Test-Path $logDir)) { New-Item -ItemType Directory -Path $logDir | Out-Null }
$logFile = Join-Path $logDir ("backend-{0}.log" -f (Get-Date -Format 'yyyyMMdd-HHmmss'))

Set-Location $repoRoot

# Spawn detached process so it survives the parent shell
$proc = Start-Process -FilePath 'powershell.exe' `
    -ArgumentList @('-NoLogo', '-NoProfile', '-Command',
        "Set-Location '$repoRoot'; uvicorn backend.main:app --port $port *>> '$logFile'") `
    -WorkingDirectory $repoRoot `
    -WindowStyle Hidden `
    -PassThru

Write-Host "Backend started detached (PID $($proc.Id)). Log: $logFile"
$proc.Id | Out-File -FilePath (Join-Path $logDir 'backend.pid') -Encoding ascii
