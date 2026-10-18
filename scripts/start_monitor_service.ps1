param([ValidateRange(1,65535)][int]$Port=8014,[ValidateSet(8010)][int]$AppPort=8010)
$ErrorActionPreference='Stop'
$projectRoot=(Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$pythonPath=Join-Path $projectRoot '.venv/Scripts/python.exe'
$dataPath=Join-Path $projectRoot 'backend/data'
$databasePath=Join-Path $dataPath 'app.db'
if(!(Test-Path -LiteralPath $pythonPath)){throw '缺少项目 .venv Python 环境'}
if(!(Test-Path -LiteralPath $databasePath)){throw '原业务数据库不存在；此脚本不会初始化或重建数据库'}
$healthUrl="http://127.0.0.1:$Port/api/monitor-service/health"
Push-Location $projectRoot
try{$expectedBuild=(& $pythonPath -c 'from backend.app.monitor_service import MONITOR_BUILD; print(MONITOR_BUILD)').Trim()}finally{Pop-Location}
$listener=Get-NetTCPConnection -State Listen -LocalPort $Port -ErrorAction SilentlyContinue
if($listener){
    $health=Invoke-RestMethod -Uri $healthUrl -TimeoutSec 3
    if($health.data.monitor_version -ne 2){throw '端口被其他服务使用，请选择其他 Port'}
    if($health.data.build -ne $expectedBuild){throw '独立监控服务是旧版本，请在其检测任务结束后单独重启该进程；原业务服务无需重启'}
}else{
    $names=@('APP_DB','OPENBLAS_NUM_THREADS','OMP_NUM_THREADS','MKL_NUM_THREADS','NUMEXPR_NUM_THREADS','PYTHONUTF8')
    $saved=@{}
    foreach($name in $names){$saved[$name]=[Environment]::GetEnvironmentVariable($name,'Process')}
    try{
        $env:APP_DB=$databasePath
        $env:OPENBLAS_NUM_THREADS='1'
        $env:OMP_NUM_THREADS='1'
        $env:MKL_NUM_THREADS='1'
        $env:NUMEXPR_NUM_THREADS='1'
        $env:PYTHONUTF8='1'
        $process=Start-Process -FilePath $pythonPath -ArgumentList @('-m','uvicorn','backend.app.monitor_service:app','--host','127.0.0.1','--port',"$Port") -WorkingDirectory $projectRoot -WindowStyle Hidden -RedirectStandardOutput (Join-Path $dataPath 'monitor-service.out.log') -RedirectStandardError (Join-Path $dataPath 'monitor-service.err.log') -PassThru
        @{pid=$process.Id;port=$Port;app_port=$AppPort}|ConvertTo-Json|Set-Content -LiteralPath (Join-Path $dataPath 'monitor-service.json') -Encoding UTF8
    }finally{foreach($name in $names){[Environment]::SetEnvironmentVariable($name,$saved[$name],'Process')}}
    $ready=$false
    for($attempt=0;$attempt -lt 30;$attempt++){
        try{$health=Invoke-RestMethod -Uri $healthUrl -TimeoutSec 1;if($health.data.monitor_version -eq 2 -and $health.data.build -eq $expectedBuild){$ready=$true;break}}catch{}
        Start-Sleep -Milliseconds 300
    }
    if(!$ready){throw '监控服务未就绪，请查看 backend/data/monitor-service.err.log'}
}
$configuration=@{app_port=$AppPort;api_origin="http://127.0.0.1:$Port"}|ConvertTo-Json
[IO.File]::WriteAllText((Join-Path $projectRoot 'frontend/monitor-runtime.local.json'),$configuration,[Text.UTF8Encoding]::new($false))
Write-Output "监控服务已就绪：$healthUrl；刷新原页面即可。原业务服务未重启。"
