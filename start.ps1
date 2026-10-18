$ErrorActionPreference='Stop'
Set-Location -LiteralPath $PSScriptRoot
$env:PYTHONUTF8='1'
$env:OPENBLAS_NUM_THREADS='1'
$env:OMP_NUM_THREADS='1'
$env:MKL_NUM_THREADS='1'
$env:NUMEXPR_NUM_THREADS='1'
if (-not (Test-Path -LiteralPath '.venv/Scripts/python.exe')) { throw '请先按 README.md 安装 Python 3.11 与 requirements.txt。' }
& .venv/Scripts/python.exe -m uvicorn backend.app.main:app --host 127.0.0.1 --port 8010 --timeout-graceful-shutdown 10
