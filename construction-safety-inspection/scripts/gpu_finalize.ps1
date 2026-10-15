# GPU finalize pipeline (PS part): wait for wheel download, then call Python
$dst = 'C:\Users\Public\torch_wheels'
$wheel = "$dst\torch-2.7.1+cu126-cp311-cp311-win_amd64.whl.full"
$total = [long]2716982502
$proj = 'D:\Desktop\ProfPractice\construction-safety-inspection'
$py = "$proj\.venv\Scripts\python.exe"

Write-Host "=== STAGE 1: wait for torch wheel ==="
$deadline = (Get-Date).AddHours(5)
while ((Get-Date) -lt $deadline) {
    $sz = (Get-Item $wheel -ErrorAction SilentlyContinue).Length
    if ($sz -eq $total) { Write-Host "WHEEL_READY"; break }
    Start-Sleep -Seconds 120
    Write-Host "WAIT_WHEEL: $([math]::Round($sz/1MB,1))MB / 2591.9MB"
}
if ((Get-Item $wheel -ErrorAction SilentlyContinue).Length -ne $total) {
    Write-Host "FATAL: wheel not ready in time"; exit 1
}

Write-Host "=== STAGE 2-6: python pipeline ==="
& $py "$proj\scripts\gpu_finalize.py"
Write-Host "=== ALL_PIPELINE_DONE ==="

