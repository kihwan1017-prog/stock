#Requires -Version 5.1
<#
.SYNOPSIS
  Startup ordering verification for StockMobileTailscaleEnsure (WRK ordering V1).
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

function Get-Task([string]$Name) {
    return Get-ScheduledTask -TaskName $Name -ErrorAction SilentlyContinue
}

$tsTask = Get-Task "StockMobileTailscaleEnsure"
$beTask = Get-Task "StockBackendProdEnsure"
$feTask = Get-Task "StockFrontendProdEnsure"

Assert-True ($null -ne $tsTask) "task_present"
Assert-True ($null -ne $beTask) "backend_task_present"
Assert-True ($null -ne $feTask) "frontend_task_present"

# C: single task only
$dup = @(Get-ScheduledTask | Where-Object { $_.TaskName -like "*Tailscale*Stock*" -or $_.TaskName -eq "StockMobileTailscaleEnsure" })
Assert-True (@($dup).Count -eq 1) "C_single_task_only"

# A: delay PT5M + Boot trigger (may FAIL until elevate)
$boot = @($tsTask.Triggers) | Where-Object { $_.CimClass.CimClassName -eq "MSFT_TaskBootTrigger" } | Select-Object -First 1
$logon = @($tsTask.Triggers) | Where-Object { $_.CimClass.CimClassName -eq "MSFT_TaskLogonTrigger" } | Select-Object -First 1
$delay = if ($null -ne $boot) { [string]$boot.Delay } else { "" }
Assert-True ($null -ne $boot -and $delay -eq "PT5M") "A_tailscale_delay_PT5M"
Assert-True ($null -eq $logon) "A_no_atlogon_primary"

# B: action unchanged path
$act = [string](@($tsTask.Actions)[0].Arguments)
Assert-True ($act -match 'ensure_stock_mobile_access\.ps1') "B_action_ensure_script"

# D/E sibling delays
$beDelay = [string](@($beTask.Triggers)[0].Delay)
$feDelay = [string](@($feTask.Triggers)[0].Delay)
Assert-True ($beDelay -eq "PT2M") "E_backend_PT2M"
Assert-True ($feDelay -eq "PT2M30S" -or $feDelay -eq "PT150S") "D_frontend_PT2M30S"

# Registration script canonical
$reg = Get-Content -LiteralPath (Join-Path $ProjectRoot "ops\register_stock_mobile_tailscale_ensure_task.ps1") -Raw
Assert-True ($reg -match 'Delay\s*=\s*"PT5M"') "reg_script_PT5M"
Assert-True ($reg -match 'AtStartup') "reg_script_AtStartup"
Assert-True ($reg -notmatch 'New-ScheduledTaskTrigger\s+-AtLogOn') "reg_script_no_AtLogOn"

# F/G/H/I: ensure when FE healthy (do not restart BE/FE)
$ensure = Join-Path $ProjectRoot "ops\ensure_stock_mobile_access.ps1"
$out = & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $ensure -ProjectRoot $ProjectRoot 2>&1 | Out-String
$code = $LASTEXITCODE
Assert-True ($code -eq 0) "F_ensure_exit0"
Assert-True ($out -match '"STOCK_SERVE_MAPPING_OK":\s*true' -or $out -match 'STOCK_SERVE_MAPPING_OK.: True') "G_mapping_ok"

$stockHttp = 0
try { $stockHttp = [int](Invoke-WebRequest -Uri "https://stock.tail3bf7b2.ts.net/" -UseBasicParsing -TimeoutSec 20).StatusCode } catch {
    if ($_.Exception.Response) { $stockHttp = [int]$_.Exception.Response.StatusCode.value__ }
}
Assert-True ($stockHttp -ge 200 -and $stockHttp -lt 400) "H_stock_https"

$lottoFp = "MISSING"
try {
    $j = & tailscale serve status --json 2>&1 | Out-String | ConvertFrom-Json
    $lottoFp = [string]$j.Web."lottolab.tail3bf7b2.ts.net:443".Handlers."/".Proxy
} catch { }
Assert-True ($lottoFp -eq "http://127.0.0.1:8765") "I_lotto_unchanged"

# J: no destructive in ensure (logic file) / register
$ensureSrc = Get-Content -LiteralPath $ensure -Raw
Assert-True ($ensureSrc -notmatch '(?m)^\s*&\s*\$\w+\s+serve\s+reset\b') "J_no_serve_reset"
Assert-True ($reg -notmatch '(?i)funnel') "J_no_funnel_in_register"
Assert-True ($reg -notmatch '(?i)set-hostname') "J_no_hostname"

Write-Host "FAILED_COUNT=$failed"
# A may fail pre-elevate — report separately
if ($failed -gt 0) {
    Write-Host "NOTE: If only A_* failed, elevate register script then re-run."
    exit 1
}
exit 0
