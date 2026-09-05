#Requires -Version 5.1
<#
.SYNOPSIS
  PowerShell Env: path remove regression tests (WRK-136).
#>
[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest
$failed = 0

function Assert-True([bool]$Cond, [string]$Name) {
    if ($Cond) { Write-Host "PASS $Name" }
    else { Write-Host "FAIL $Name"; $script:failed++ }
}

# A: Env path remove 정상
$env:TEST_STOCK_ENV = "x"
Assert-True (Test-Path Env:TEST_STOCK_ENV) "A_setup_exists"
Remove-Item -LiteralPath ('Env:' + 'TEST_STOCK_ENV') -ErrorAction SilentlyContinue
Assert-True (-not (Test-Path Env:TEST_STOCK_ENV)) "A_env_remove"

# B: missing env key 무오류
Remove-Item -LiteralPath ('Env:' + 'TEST_STOCK_ENV_MISSING_XYZ') -ErrorAction SilentlyContinue
Assert-True $true "B_missing_env_no_throw"

# C: multiple env keys 정상
$keys = @('TEST_STOCK_ENV_A', 'TEST_STOCK_ENV_B', 'TEST_STOCK_ENV_C')
foreach ($k in $keys) { Set-Item -Path ('Env:' + $k) -Value '1' }
foreach ($k in $keys) {
    if ($k -notmatch '^[A-Za-z_][A-Za-z0-9_]*$') { throw "bad key $k" }
    Remove-Item -LiteralPath ('Env:' + $k) -ErrorAction SilentlyContinue
}
$allGone = $true
foreach ($k in $keys) { if (Test-Path -Path ('Env:' + $k)) { $allGone = $false } }
Assert-True $allGone "C_multi_env_remove"

# D: startup script parser — extract Remove-Item line pattern from prod script
$prod = Join-Path (Split-Path $PSScriptRoot -Parent) "ops\start_backend_prod.ps1"
if (-not (Test-Path $prod)) { $prod = "d:\Projects\stock-platform\ops\start_backend_prod.ps1" }
$raw = Get-Content -LiteralPath $prod -Raw
Assert-True ($raw -match "Remove-Item -LiteralPath \('Env:' \+") "D_prod_uses_single_quoted_Env"
Assert-True ($raw -notmatch 'Remove-Item -LiteralPath \("Env:" \+') "D_prod_no_double_quoted_Env"
$prodTokens = $null
$prodErrs = $null
$null = [System.Management.Automation.Language.Parser]::ParseFile($prod, [ref]$prodTokens, [ref]$prodErrs)
Assert-True (($null -eq $prodErrs) -or (@($prodErrs).Count -eq 0)) "D_prod_parse_errors_zero"

$dev = "d:\Projects\stock-platform\ops\dev\start-dev.ps1"
$devRaw = Get-Content -LiteralPath $dev -Raw
Assert-True ($devRaw -match "Remove-Item -LiteralPath \('Env:' \+") "D_dev_uses_single_quoted_Env"
Assert-True ($devRaw -notmatch 'Remove-Item -LiteralPath \("Env:" \+') "D_dev_no_double_quoted_Env"

$fixTokens = $null
$fixErrs = $null
$fixed = "Remove-Item -LiteralPath ('Env:' + `$key) -ErrorAction SilentlyContinue"
$null = [System.Management.Automation.Language.Parser]::ParseInput($fixed, [ref]$fixTokens, [ref]$fixErrs)
Assert-True (($null -eq $fixErrs) -or (@($fixErrs).Count -eq 0)) "D_fixed_snippet_parse_ok"

# E: task registration still valid (if present)
$task = Get-ScheduledTask -TaskName "StockBackendProdEnsure" -ErrorAction SilentlyContinue
if ($null -eq $task) {
    Write-Host "SKIP E_task_absent (elevate register residual)"
} else {
    Assert-True ($task.State -in @('Ready','Running')) "E_task_state"
    $action = ($task.Actions | Select-Object -First 1).Arguments
    Assert-True ($action -match 'start_backend_prod\.ps1') "E_task_action_prod"
}

Write-Host "FAILED_COUNT=$failed"
if ($failed -gt 0) { exit 1 }
exit 0
