#Requires -Version 5.1
# Static checks: production root isolation helper + start_backend_prod wiring.
param([string]$ProjectRoot = "")

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

function Assert-True([bool]$Cond, [string]$Name) {
    if (-not $Cond) { throw "ASSERT_FAIL:$Name" }
    Write-Host "OK $Name"
}

if ([string]::IsNullOrWhiteSpace($ProjectRoot)) {
    $ProjectRoot = Split-Path -Parent $PSScriptRoot
}

$resolve = Join-Path $ProjectRoot "ops\resolve_production_app_root.ps1"
$start = Join-Path $ProjectRoot "ops\start_backend_prod.ps1"
$reg = Join-Path $ProjectRoot "ops\register_stock_backend_prod_startup_task.ps1"

Assert-True (Test-Path -LiteralPath $resolve) "resolve_script_exists"
Assert-True (Test-Path -LiteralPath $start) "start_script_exists"

$resolveRaw = Get-Content -LiteralPath $resolve -Raw
Assert-True ($resolveRaw -match 'STOCK_PLATFORM_PRODUCTION_ROOT') "resolve_env_key"
Assert-True ($resolveRaw -match 'stock-platform-runtime') "resolve_default_runtime_path"

$startRaw = Get-Content -LiteralPath $start -Raw
Assert-True ($startRaw -match 'resolve_production_app_root\.ps1') "start_calls_resolve"
Assert-True ($startRaw -match 'production_loaded_commit') "start_writes_loaded_commit"
Assert-True ($startRaw -match 'VenvPython') "start_venv_python"

$regRaw = Get-Content -LiteralPath $reg -Raw
Assert-True ($regRaw -match 'resolve_production_app_root\.ps1') "register_calls_resolve"

# Prefer PreferredRoot when valid
$tmp = Join-Path $env:TEMP ("sp_prod_root_probe_" + [guid]::NewGuid().ToString("N"))
New-Item -ItemType Directory -Path (Join-Path $tmp "src\stock_platform\api") -Force | Out-Null
New-Item -ItemType Directory -Path (Join-Path $tmp "ops") -Force | Out-Null
Set-Content -LiteralPath (Join-Path $tmp "src\stock_platform\api\main.py") -Value "# probe" -Encoding ascii
Copy-Item -LiteralPath $start -Destination (Join-Path $tmp "ops\start_backend_prod.ps1")
$resolved = & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $resolve -PreferredRoot $tmp
Assert-True (($resolved.Trim() -ieq $tmp)) "preferred_root_wins"
Remove-Item -LiteralPath $tmp -Recurse -Force -ErrorAction SilentlyContinue

Write-Host "ALL_OK"
exit 0
