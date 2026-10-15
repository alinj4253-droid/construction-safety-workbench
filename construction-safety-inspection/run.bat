@echo off
rem NOTE: keep this file ASCII-only. cmd.exe parses .bat with the system
rem codepage (GBK); non-ASCII bytes can shift parsing and break commands.
cd /d "%~dp0"
echo ============================================
echo   Construction Site Safety Inspection System
echo   UI: http://127.0.0.1:7860
echo   (browser opens automatically)
echo ============================================
if not exist ".venv\Scripts\python.exe" (
    echo [ERROR] .venv not found. Read README.md first.
    pause
    exit /b 1
)
".venv\Scripts\python.exe" -m app.ui.app
echo.
echo Server stopped.
pause
