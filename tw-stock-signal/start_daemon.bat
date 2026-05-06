@echo off
cd /d "C:\Users\sfudally\Desktop\code test\tw-stock-signal"
title tw-stock-signal daemon + bot

:loop
echo ==========================================
echo  台股 ABC 選股 — Daemon + Telegram Bot
echo ==========================================
echo  排程：07:00 抓資料 / 07:30 分析 / 08:00 日報
echo  Bot：直接在 Telegram 輸入股票代號查詢
echo  [自動重啟已啟用] 崩潰後 5 秒重啟
echo ==========================================
echo.

"C:\Users\sfudally\AppData\Local\Programs\Python\Python313\python.exe" main.py --daemon

echo.
echo [%date% %time%] Bot stopped or crashed. Restarting in 5 seconds...
timeout /t 5 /nobreak >nul
goto loop
