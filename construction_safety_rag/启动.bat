@echo off
cd /d "%~dp0"
echo 正在启动施工安全证据助手 RAG...
python -m uvicorn app.api:app --host 127.0.0.1 --port 8010
pause
