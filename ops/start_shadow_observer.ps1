#Requires -Version 5.1
<#
.SYNOPSIS
  PAPER SHADOW observer 시작. 주문/LIVE/ARM/AUTO 없음.
#>
[CmdletBinding()]
param(
    [string]$ProjectRoot = "",
    [int]$Limit = 36,
    [int]$LoopSeconds = 0
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

if ([string]::IsNullOrWhiteSpace($ProjectRoot)) {
    $ProjectRoot = Split-Path -Parent $PSScriptRoot
}

$PidFile = Join-Path $ProjectRoot ".run\shadow-observer.pid"
if (Test-Path -LiteralPath $PidFile) {
    $raw = (Get-Content -LiteralPath $PidFile -Raw).Trim()
    if ($raw -match "^\d+$") {
        $existing = Get-Process -Id ([int]$raw) -ErrorAction SilentlyContinue
        if ($null -ne $existing) {
            Write-Host "[shadow-observer] already running pid=$raw"
            exit 0
        }
        Remove-Item -LiteralPath $PidFile -Force -ErrorAction SilentlyContinue
        Write-Host "[shadow-observer] removed stale pid=$raw"
    }
}

foreach ($name in @(
    "STOCK_PLATFORM_DISABLE_ENV_FILE",
    "STOCK_PLATFORM_TESTING",
    "STOCK_PLATFORM_TEST_DATABASE_URL",
    "APP_ENV",
    "DB_NAME",
    "DB_HOST",
    "DB_PORT",
    "DB_USER",
    "DB_PASSWORD",
    "DATABASE_URL"
)) {
    Remove-Item "Env:$name" -ErrorAction SilentlyContinue
}
$env:SHADOW_OBSERVATION_ONLY = "true"
$env:PYTHONPATH = Join-Path $ProjectRoot "src"
$env:STOCK_PLATFORM_ENV_FILE = "E:\StockTrading\secrets\stock-platform.env"
$python = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
$runner = Join-Path $ProjectRoot "src\stock_platform\operation\paper_shadow_observer\runner.py"
$argsList = @($runner, "--limit", "$Limit")
if ($LoopSeconds -gt 0) {
    $argsList += @("--loop-seconds", "$LoopSeconds")
} else {
    $argsList += "--once"
}

$obsDir = Join-Path $ProjectRoot ".run\paper-shadow-observation"
New-Item -ItemType Directory -Force -Path $obsDir | Out-Null
$outLog = Join-Path $obsDir "observer.out.log"
$errLog = Join-Path $obsDir "observer.err.log"
Write-Host "[shadow-observer] starting observation-only runner"
Start-Process -FilePath $python -ArgumentList $argsList -WorkingDirectory $ProjectRoot -WindowStyle Hidden -RedirectStandardOutput $outLog -RedirectStandardError $errLog
Write-Host "[shadow-observer] launched. LIVE/ARM/AUTO not touched."
