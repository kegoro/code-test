@echo off
REM SMC bot watchdog - auto-restart on crash or network drop.
REM Uses system Python313 (has requests/pandas/shioaji).
REM Launched hidden by launch_smc_bot.vbs.
REM IMPORTANT: keep this file ASCII-only. Chinese text here breaks cmd.exe (Big5 vs UTF-8) and the bot never starts.
chcp 65001 >nul
cd /d "C:\Users\sfudally\Desktop\code test"
:loop
"C:\Users\sfudally\AppData\Local\Programs\Python\Python313\python.exe" -m backend.smc_bot >> "_smc_bot.watchdog.log" 2>&1
echo [%date% %time%] bot exited, restart in 5s >> "_smc_bot.watchdog.log"
timeout /t 5 /nobreak >nul
goto loop
