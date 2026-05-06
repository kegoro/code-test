$ErrorActionPreference = 'SilentlyContinue'
$proj = "C:\Users\sfudally\Desktop\code test\tw-stock-signal"
$front = "$proj\frontend"
$logFile = "$env:TEMP\cloudflared_tunnel.log"

if (Test-Path $logFile) { Remove-Item $logFile -Force }

Write-Host ""
Write-Host "  [1/4] 啟動後端 API..." -ForegroundColor Cyan
Start-Process powershell -ArgumentList "-NoExit", "-Command", "Set-Location '$proj'; & '.\.venv\Scripts\Activate.ps1'; uvicorn api.main:app --host 0.0.0.0 --port 8000"

Start-Sleep 3

Write-Host "  [2/4] 啟動前端..." -ForegroundColor Cyan
Start-Process powershell -ArgumentList "-NoExit", "-Command", "Set-Location '$front'; npm run dev"

Start-Sleep 5

Write-Host "  [3/4] 建立公開網址 (Cloudflare Tunnel)..." -ForegroundColor Cyan
Start-Process cloudflared -ArgumentList "tunnel", "--url", "http://localhost:5173", "--logfile", $logFile -WindowStyle Minimized

Write-Host "  [4/4] 等待網址產生..." -ForegroundColor Cyan
$publicUrl = $null
$timeout = 30
for ($i = 0; $i -lt $timeout; $i++) {
    Start-Sleep 1
    if (Test-Path $logFile) {
        $content = Get-Content $logFile -Raw
        if ($content -match 'https://[a-z0-9-]+\.trycloudflare\.com') {
            $publicUrl = $matches[0]
            break
        }
    }
}

Clear-Host
Write-Host ""
Write-Host "============================================" -ForegroundColor Green
Write-Host "        籌碼K線 已啟動完成" -ForegroundColor Green
Write-Host "============================================" -ForegroundColor Green
Write-Host ""
Write-Host "  電腦本機: http://localhost:5173" -ForegroundColor White
Write-Host ""

if ($publicUrl) {
    Write-Host "  手機外網 (4G/5G/任何網路都能用):" -ForegroundColor Yellow
    Write-Host "  $publicUrl" -ForegroundColor White -BackgroundColor DarkBlue
    Write-Host ""
    Set-Clipboard -Value $publicUrl
    Write-Host "  [已複製到剪貼簿]" -ForegroundColor Green

    $qrUrl = "https://api.qrserver.com/v1/create-qr-code/?size=400x400&data=" + [System.Uri]::EscapeDataString($publicUrl)
    Write-Host "  正在開啟 QR code，請用手機掃描..." -ForegroundColor Cyan
    Start-Process $qrUrl
    Start-Sleep 1
    Start-Process "http://localhost:5173"
} else {
    Write-Host "  [警告] 公開網址產生失敗，請檢查 cloudflared 視窗" -ForegroundColor Red
    Start-Process "http://localhost:5173"
}

Write-Host ""
Write-Host "  關閉所有黑色視窗即可停止服務" -ForegroundColor DarkGray
Write-Host ""
Write-Host "============================================" -ForegroundColor Green
Write-Host ""
Read-Host "  按 Enter 關閉此視窗"
