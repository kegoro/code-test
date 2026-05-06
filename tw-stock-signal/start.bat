@echo off
REM ============================================================
REM  tw-stock-signal — Windows startup script
REM  Run this file to start the scheduler in daemon mode.
REM  To auto-start on login, import task_scheduler.xml into
REM  Windows Task Scheduler (see instructions below).
REM ============================================================

cd /d "%~dp0"

REM Activate virtual environment
if exist ".venv\Scripts\activate.bat" (
    call .venv\Scripts\activate.bat
) else (
    echo [ERROR] .venv not found. Run: python -m venv .venv ^&^& pip install -r requirements.txt
    pause
    exit /b 1
)

REM Start the scheduler
echo [tw-stock-signal] Starting daemon scheduler...
python main.py --daemon

REM If it exits unexpectedly, pause so you can read the error
pause
