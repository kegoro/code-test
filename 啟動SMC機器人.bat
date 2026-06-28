@echo off
chcp 65001 >nul
cd /d "C:\Users\sfudally\Desktop\code test"
title SMC bot - do not close

:loop
echo [%date% %time%] SMC bot starting... output -^> %TEMP%\smc_bot.log
"C:\Users\sfudally\AppData\Local\Programs\Python\Python313\python.exe" -m backend.smc_bot >> "%TEMP%\smc_bot.log" 2>&1
echo [%date% %time%] stopped or crashed. restart in 5s...
timeout /t 5 /nobreak >nul
goto loop
