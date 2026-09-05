#Requires -Version 5.1
<#
.SYNOPSIS
  StockBackendProdEnsure AtStartup + StockBackendProdHealthEnsure PT5M checks.
#>
[CmdletBinding()]
param(
    [string]$ProjectRoot = ""
)

$ErrorActionPreference = "Continue"
Set-StrictMode -Version Latest
if ([string]::IsNullOrWhiteSpace($ProjectRoot)) {
    $ProjectRoot = Split-Path -Parent $PSScriptRoot
}

$failed = 0
function Assert-True([bool]$Cond, [string]$Name) {
    if ($Cond) { Write-Host "PASS $Name" }
    else { Write-Host "FAIL $Name"; $script:failed++ }
}

$regPath = Join-Path $ProjectRoot "ops\register_stock_backend_prod_startup_task.ps1"
$reg = Get-Content -LiteralPath $regPath -Raw
Assert-True ($reg -match 'AtStartup') "reg_AtStartup"
Assert-True ($reg -match 'StockBackendProdHealthEnsure') "reg_health_task_name"
Assert-True ($reg -match 'RepetitionInterval') "reg_RepetitionInterval"
Assert-True ($reg -match 'WakeToRun') "reg_WakeToRun"
Assert-True ($reg -match 'start_backend_prod\.ps1') "reg_start_backend_prod"

$bootTask = Get-ScheduledTask -TaskName "StockBackendProdEnsure" -ErrorAction SilentlyContinue
Assert-True ($null -ne $bootTask) "boot_task_present"
if ($null -ne $bootTask) {
    $boot = @($bootTask.Triggers) | Where-Object { $_.CimClass.CimClassName -eq "MSFT_TaskBootTrigger" } | Select-Object -First 1
    Assert-True ($null -ne $boot) "live_boot_trigger"
}

$health = Get-ScheduledTask -TaskName "StockBackendProdHealthEnsure" -ErrorAction SilentlyContinue
Assert-True ($null -ne $health) "health_task_present"
if ($null -ne $health) {
    $hasRep = $false
    foreach ($tr in @($health.Triggers)) {
        if ($null -ne $tr.Repetition -and [string]$tr.Repetition.Interval -eq "PT5M") {
            $hasRep = $true
        }
    }
    Assert-True $hasRep "live_health_PT5M"
    Assert-True ([bool]$health.Settings.WakeToRun) "live_health_WakeToRun"
}

# start_backend_prod idempotent when healthy
$start = Join-Path $ProjectRoot "ops\start_backend_prod.ps1"
$out = & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $start -ProjectRoot $ProjectRoot 2>&1 | Out-String
Assert-True ($LASTEXITCODE -eq 0) "ensure_idempotent_exit0"
Assert-True ($out -match 'already listening|READY') "ensure_idempotent_skip_or_ready"

if ($failed -gt 0) {
    Write-Host "RESULT FAIL count=$failed"
    exit 1
}
Write-Host "RESULT PASS"
exit 0
