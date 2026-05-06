@echo off
echo ================================================
echo   籌碼K線 Dashboard 啟動中...
echo ================================================

cd /d "%~dp0"

echo.
echo [1/2] 啟動後端 API (port 8000)...
start "API Server" cmd /k "cd /d "%~dp0" && .venv\Scripts\python.exe -m uvicorn api.main:app --reload --port 8000"

echo.
echo [2/2] 啟動前端 (port 5173)...
cd frontend
start "Frontend" cmd /k "npm run dev"

echo.
echo ================================================
echo   後端：http://localhost:8000
echo   前端：http://localhost:5173
echo ================================================
echo.
echo 請等待 5-10 秒後在瀏覽器開啟 http://localhost:5173
pause
