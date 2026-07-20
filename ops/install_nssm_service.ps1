# Stock Platform API — NSSM Windows Service 등록
#
# 사전 조건:
#   1) NSSM 설치 후 PATH 에 포함 (https://nssm.cc/download)
#   2) 관리자 PowerShell 에서 실행
#   3) E:\StockTrading\secrets\stock-platform.env 준비
#   4) .venv / pip install 완료
#
# 사용:
#   .\ops\install_nssm_service.ps1
#   .\ops\install_nssm_service.ps1 -ServiceName StockPlatformAPI -Port 8000

param(
    [string]$ServiceName = "StockPlatformAPI",
    [string]$HostAddress = "127.0.0.1",
    [int]$Port = 8000,
    [string]$OpsRoot = "E:\StockTrading"
)

$ErrorActionPreference = "Stop"

function Require-Admin {
    $id = [Security.Principal.WindowsIdentity]::GetCurrent()
    $p = New-Object Security.Principal.WindowsPrincipal($id)
    if (-not $p.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
        throw "관리자 권한 PowerShell 에서 실행하세요."
    }
}

Require-Admin

$nssm = Get-Command nssm -ErrorAction SilentlyContinue
if (-not $nssm) {
    throw "nssm 명령을 찾을 수 없습니다. NSSM 을 설치하고 PATH 에 추가하세요."
}

$projectRoot = Split-Path -Parent $PSScriptRoot
$python = Join-Path $projectRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $python)) {
    throw "venv python 없음: $python"
}

$logDir = Join-Path $OpsRoot "logs"
$runDir = Join-Path $PSScriptRoot "run"
New-Item -ItemType Directory -Force -Path $logDir, $runDir | Out-Null

$existing = Get-Service -Name $ServiceName -ErrorAction SilentlyContinue
if ($existing) {
    Write-Host "[info] 기존 서비스 중지/제거: $ServiceName"
    & nssm stop $ServiceName
    & nssm remove $ServiceName confirm
}

$appParams = "-m uvicorn stock_platform.api.main:app --host $HostAddress --port $Port --app-dir src"
$stdout = Join-Path $logDir "service_stdout.log"
$stderr = Join-Path $logDir "service_stderr.log"

Write-Host "[install] $ServiceName"
& nssm install $ServiceName $python $appParams
& nssm set $ServiceName AppDirectory $projectRoot
& nssm set $ServiceName AppEnvironmentExtra "PYTHONPATH=$projectRoot\src"
& nssm set $ServiceName DisplayName "Stock Platform API"
& nssm set $ServiceName Description "FastAPI stock-platform (uvicorn)"
& nssm set $ServiceName Start SERVICE_AUTO_START
& nssm set $ServiceName AppStdout $stdout
& nssm set $ServiceName AppStderr $stderr
& nssm set $ServiceName AppRotateFiles 1
& nssm set $ServiceName AppRotateBytes 10485760
& nssm set $ServiceName AppRotateOnline 1
& nssm set $ServiceName AppExit Default Restart
& nssm set $ServiceName AppRestartDelay 5000
& nssm set $ServiceName AppThrottle 1500

Write-Host "[start] $ServiceName"
& nssm start $ServiceName

Write-Host "[OK] 서비스 등록 완료"
Write-Host "     nssm status $ServiceName"
Write-Host "     logs: $stdout / $stderr"
Write-Host "     health: http://${HostAddress}:${Port}/health"
