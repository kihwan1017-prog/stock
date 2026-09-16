#Requires -Version 5.1
<#
.SYNOPSIS
  개발용 Backend만 기동 (uvicorn --reload --reload-dir src).
  PAPER/development only — REAL LIVE/ARM 금지 (APP_RUNTIME_MODE=development).
  LIVE 운영에는 ops/start_backend_prod.ps1 사용.
#>
[CmdletBinding()]
param(
    [string]$ProjectRoot = "",
    [string]$EnvFile = "E:\StockTrading\secrets\stock-platform.env",
    [string]$BackendHost = "127.0.0.1",
    [int]$BackendPort = 8000
)

$ErrorActionPreference = "Stop"
# Full stack (FE+BE) 는 기존 ops/dev/start-dev.ps1
# 이 스크립트는 backend-only reload 개발용 별칭.
$here = $PSScriptRoot
$dev = Join-Path $here "dev\start-dev.ps1"
if (-not (Test-Path -LiteralPath $dev)) {
    throw "missing $dev"
}
Write-Host "[start-backend-dev] DEV ONLY — REAL trading blocked under hot-reload (History #92)"
Write-Host "[start-backend-dev] delegating to ops/dev/start-dev.ps1 (includes --reload --reload-dir src)"
& $dev -ProjectRoot $ProjectRoot -EnvFile $EnvFile -BackendHost $BackendHost -BackendPort $BackendPort
