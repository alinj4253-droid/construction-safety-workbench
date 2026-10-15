@echo off
rem ASCII-only on purpose (see run.bat note)
title System Status Dashboard
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
    echo [ERROR] .venv not found.
    pause
    exit /b 1
)
".venv\Scripts\python.exe" "scripts\progress_dashboard.py"
echo.
pause
