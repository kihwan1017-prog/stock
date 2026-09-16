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
    }
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

Write-Host "[shadow-observer] starting observation-only runner"
Start-Process -FilePath $python -ArgumentList $argsList -WorkingDirectory $ProjectRoot -WindowStyle Hidden
Write-Host "[shadow-observer] launched. LIVE/ARM/AUTO not touched."
