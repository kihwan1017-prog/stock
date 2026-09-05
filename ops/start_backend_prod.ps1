#Requires -Version 5.1
<#
.SYNOPSIS
  LIVE/운영용 Backend 기동 — uvicorn --reload 금지, workers=1 (in-memory Hub/Worker).
.DESCRIPTION
  Canonical production entrypoint.
  Env: E:\StockTrading\secrets\stock-platform.env (기본)
  Source file change로는 restart 하지 않음.
#>
[CmdletBinding()]
param(
    [string]$ProjectRoot = "",
    [string]$EnvFile = "E:\StockTrading\secrets\stock-platform.env",
    [string]$BackendHost = "127.0.0.1",
    [int]$BackendPort = 8000,
    [int]$ReadyTimeoutSec = 120,
    [switch]$Force
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

function Write-Step([string]$Message) {
    Write-Host "[start-backend-prod] $Message"
}

if ([string]::IsNullOrWhiteSpace($ProjectRoot)) {
    $ProjectRoot = Split-Path -Parent $PSScriptRoot
    if ((Split-Path -Leaf $PSScriptRoot) -ieq "ops") {
        $ProjectRoot = Split-Path -Parent $PSScriptRoot
    }
}

$VenvPython = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $VenvPython)) {
    throw "venv python missing: $VenvPython"
}
if (-not (Test-Path -LiteralPath $EnvFile)) {
    throw "env file missing: $EnvFile"
}

$RunDir = Join-Path $ProjectRoot ".run"
$LogDir = Join-Path $ProjectRoot "logs"
New-Item -ItemType Directory -Force -Path $RunDir, $LogDir | Out-Null
$BackendPidFile = Join-Path $RunDir "backend.pid"
$ListenPidFile = Join-Path $RunDir "backend.listen.pid"
$BackendLog = Join-Path $LogDir ("uvicorn_prod_{0:yyyyMMdd_HHmmss}.log" -f (Get-Date))

function Test-PortListening([int]$Port) {
    try {
        $conn = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue |
            Select-Object -First 1
        if ($null -ne $conn -and $conn.OwningProcess -gt 0) {
            return [int]$conn.OwningProcess
        }
    } catch { }
    $lines = netstat -ano | Select-String -Pattern ":$Port\s+.*LISTENING"
    foreach ($line in $lines) {
        $parts = ($line.ToString() -split "\s+") | Where-Object { $_ -ne "" }
        if ($parts.Count -ge 5) { return [int]$parts[-1] }
    }
    return $null
}

function Test-HttpOk([string]$Url) {
    try {
        $resp = Invoke-WebRequest -Uri $Url -UseBasicParsing -TimeoutSec 3
        return ($resp.StatusCode -ge 200 -and $resp.StatusCode -lt 500)
    } catch { return $false }
}

$existing = Test-PortListening $BackendPort
if ($null -ne $existing -and -not $Force) {
    if (Test-HttpOk "http://${BackendHost}:${BackendPort}/health/live") {
        Write-Step "already listening PID=$existing — skip (use -Force to replace)"
        Set-Content -LiteralPath $ListenPidFile -Value $existing -Encoding ascii
        exit 0
    }
}

if ($Force -and $null -ne $existing) {
    Write-Step "Force: stopping port $BackendPort listener via ops/stop_backend.ps1"
    & (Join-Path $PSScriptRoot "stop_backend.ps1") -BackendPort $BackendPort
    Start-Sleep -Seconds 2
}

Write-Step "NO --reload · workers=1 · env=$EnvFile · APP_RUNTIME_MODE=production"

# Child 스크립트는 single-quoted here-string으로 작성한다.
# expandable @" "@ 는 주석의 bare $key 까지 outer StrictMode에서 평가되어 실패한다 (H136 residual / H138).
# outer 값은 PLACEHOLDER만 Replace — Invoke-Expression 금지.
$pythonPathSrc = Join-Path $ProjectRoot "src"
$childScriptPath = Join-Path $RunDir "backend_prod_child.ps1"
$childTemplate = @'
#Requires -Version 5.1
$ErrorActionPreference = "Continue"
Set-StrictMode -Version Latest
Set-Location -LiteralPath "__PROJECT_ROOT__"
$env:STOCK_PLATFORM_ENV_FILE = "__ENV_FILE__"
$env:PYTHONPATH = "__PYTHONPATH__"
$env:STOCK_PLATFORM_LAUNCH_MODE = "PROD"
$env:APP_RUNTIME_MODE = "production"
$env:HOT_RELOAD_ENABLED = "false"
$liveEnvKeys = @(
    "GLOBAL_LIVE_ORDER_ENABLED",
    "UPBIT_LIVE_ORDER_ENABLED",
    "UPBIT_USE_MOCK",
    "LIVE_OUTBOX_WORKER_ENABLED",
    "LIVE_OUTBOX_WORKER_AUTO_START",
    "KIWOOM_LIVE_ORDER_ENABLED",
    "KIWOOM_USE_MOCK"
)
foreach ($key in $liveEnvKeys) {
    if ($key -notmatch "^[A-Za-z_][A-Za-z0-9_]*$") { continue }
    # Env: + $key 는 child scope에서만 평가 (outer expansion 경계 밖)
    Remove-Item -LiteralPath ('Env:' + $key) -ErrorAction SilentlyContinue
}
# production: never pass --reload
& "__VENV_PYTHON__" -m uvicorn stock_platform.api.main:app --host __BACKEND_HOST__ --port __BACKEND_PORT__ --app-dir src --workers 1 *>> "__BACKEND_LOG__"
'@

$childBody = $childTemplate
$childReplacements = [ordered]@{
    "__PROJECT_ROOT__"  = $ProjectRoot
    "__ENV_FILE__"      = $EnvFile
    "__PYTHONPATH__"    = $pythonPathSrc
    "__VENV_PYTHON__"   = $VenvPython
    "__BACKEND_HOST__"  = $BackendHost
    "__BACKEND_PORT__"  = [string]$BackendPort
    "__BACKEND_LOG__"   = $BackendLog
}
foreach ($placeholder in $childReplacements.Keys) {
    $childBody = $childBody.Replace([string]$placeholder, [string]$childReplacements[$placeholder])
}
if ($childBody -match "__[A-Z0-9_]+__") {
    throw "unresolved child script placeholder remains"
}
# UTF8 BOM 없는 바이트로 기록 (PowerShell 5.1 -File 호환)
[System.IO.File]::WriteAllText($childScriptPath, $childBody, (New-Object System.Text.UTF8Encoding $false))

$backendProc = Start-Process -FilePath "powershell.exe" `
    -ArgumentList @("-NoProfile", "-ExecutionPolicy", "Bypass", "-File", $childScriptPath) `
    -WorkingDirectory $ProjectRoot `
    -WindowStyle Minimized `
    -PassThru
Set-Content -LiteralPath $BackendPidFile -Value $backendProc.Id -Encoding ascii
Write-Step "launcher PID=$($backendProc.Id) child=$childScriptPath log=$BackendLog"

$deadline = (Get-Date).AddSeconds($ReadyTimeoutSec)
$health = "http://${BackendHost}:${BackendPort}/health/live"
while ((Get-Date) -lt $deadline) {
    if (Test-HttpOk $health) {
        $listen = Test-PortListening $BackendPort
        if ($null -ne $listen) {
            Set-Content -LiteralPath $ListenPidFile -Value $listen -Encoding ascii
        }
        Write-Step "READY health=$health listenPID=$listen"
        exit 0
    }
    Start-Sleep -Milliseconds 800
}
throw "backend health timeout: $health (log=$BackendLog)"
