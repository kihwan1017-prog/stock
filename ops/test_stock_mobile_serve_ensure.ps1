#Requires -Version 5.1
<#
.SYNOPSIS
  Stock Tailscale Serve ensure — focused test matrix (no trading mutation).
.NOTES
  WRK-20260906-TAILSCALE-STOCK-SERVE-RECURRENCE-DURABLE-FIX-V1
  serve reset 금지. Lotto fingerprint 보존 검증.
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

$ensure = Join-Path $ProjectRoot "ops\ensure_stock_mobile_access.ps1"
$ts = "C:\Program Files\Tailscale\tailscale.exe"
if (-not (Test-Path $ts)) { $ts = (Get-Command tailscale).Source }

function Invoke-Ensure {
    param([string[]]$ExtraArgs = @())
    $prev = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    $allArgs = @("-NoProfile", "-ExecutionPolicy", "Bypass", "-File", $ensure, "-ProjectRoot", $ProjectRoot) + $ExtraArgs
    $out = & powershell.exe @allArgs 2>&1 | Out-String
    $ErrorActionPreference = $prev
    $m = [regex]::Matches($out, '(?s)\{[^{}]*"FINAL_VERDICT"[^{}]*\}')
    if ($m.Count -eq 0) { throw "ensure produced no JSON: $out" }
    return ($m[$m.Count - 1].Value | ConvertFrom-Json)
}

function Get-LottoFp {
    $prev = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    $j = & $ts serve status --json 2>&1 | Out-String | ConvertFrom-Json
    $ErrorActionPreference = $prev
    $key = "lottolab.tail3bf7b2.ts.net:443"
    if ($null -eq $j -or $null -eq (Get-Member -InputObject $j -Name Web -ErrorAction SilentlyContinue)) { return "MISSING" }
    $prop = $j.Web.PSObject.Properties | Where-Object { $_.Name -eq $key } | Select-Object -First 1
    if ($null -eq $prop) { return "MISSING" }
    try { return [string]$prop.Value.Handlers."/".Proxy } catch { return "MISSING" }
}

function Get-StockPresent {
    $prev = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    $j = & $ts serve status --json 2>&1 | Out-String | ConvertFrom-Json
    $ErrorActionPreference = $prev
    if ($null -eq $j) { return $false }
    $svc = $j.PSObject.Properties | Where-Object { $_.Name -eq "Services" } | Select-Object -First 1
    if ($null -eq $svc) { return $false }
    $stock = $svc.Value.PSObject.Properties | Where-Object { $_.Name -eq "svc:stock" } | Select-Object -First 1
    return ($null -ne $stock)
}

function Invoke-TsSafe([string[]]$TsArgs) {
    $prev = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    & $ts @TsArgs 2>&1 | Out-String | Out-Null
    $ErrorActionPreference = $prev
}

$results = [ordered]@{}
$failed = 0

# 사전: stock+lotto healthy baseline
$null = Invoke-Ensure
if (-not (Get-StockPresent)) { $null = Invoke-Ensure }

Write-Host "CASE1 healthy ensure no-change"
$r1 = Invoke-Ensure
$results.CASE1 = "$($r1.FINAL_VERDICT)/$($r1.ACTION)/lottoChanged=$($r1.LOTTO_CONFIG_CHANGED)"
if ($r1.FINAL_VERDICT -ne "ALREADY_OK" -or $r1.CHANGED -ne $false) { $failed++ }

Write-Host "CASE6 repeat 10x identical (SkipHttpProbe)"
$fps = New-Object System.Collections.Generic.List[string]
for ($i = 0; $i -lt 10; $i++) {
    $null = Invoke-Ensure -ExtraArgs @("-SkipHttpProbe")
    $prev = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    [void]$fps.Add(((& $ts serve status --json 2>&1 | Out-String).Trim()))
    $ErrorActionPreference = $prev
}
$uniq = @($fps | Select-Object -Unique).Count
$results.CASE6 = "uniqueConfigs=$uniq"
if ($uniq -ne 1) { $failed++ }

Write-Host "CASE2 stock missing + restore"
$lottoBefore = Get-LottoFp
Invoke-TsSafe @("serve", "clear", "svc:stock")
Start-Sleep -Seconds 2
$missing = -not (Get-StockPresent)
$r2 = Invoke-Ensure
$lottoAfter = Get-LottoFp
$results.CASE2 = "cleared=$missing/$($r2.FINAL_VERDICT)/$($r2.ACTION)/lottoSame=$($lottoBefore -eq $lottoAfter)"
if (-not $missing -or $r2.FINAL_VERDICT -ne "RESTORED" -or $lottoBefore -ne $lottoAfter) { $failed++ }

Write-Host "CASE3 wrong target drift repair"
Invoke-TsSafe @("serve", "--bg", "--service=svc:stock", "--https=443", "http://127.0.0.1:3999")
Start-Sleep -Seconds 2
$r3 = Invoke-Ensure
$results.CASE3 = "$($r3.FINAL_VERDICT)/endpoint=$($r3.STOCK_ENDPOINT)/driftWasRepaired=$($r3.CHANGED)"
if ($r3.STOCK_ENDPOINT -ne "http://127.0.0.1:3000" -or $r3.FINAL_VERDICT -ne "RESTORED") { $failed++ }

Write-Host "CASE4 ensure after healthy"
$r4 = Invoke-Ensure
$results.CASE4 = "$($r4.FINAL_VERDICT)/$($r4.ACTION)"
if ($r4.FINAL_VERDICT -ne "ALREADY_OK") { $failed++ }

Write-Host "CASE5 lotto proxy still 8765"
$lp = Get-LottoFp
$results.CASE5 = "lottoProxy=$lp"
if ($lp -ne "http://127.0.0.1:8765") { $failed++ }

$results.CASE7 = "SKIPPED_SAFETY_NO_TS_RESTART"

Write-Host "CASE8 frontend down — config not destroyed"
$r8 = Invoke-Ensure -ExtraArgs @("-FrontendPort", "39998", "-SkipHttpProbe")
$results.CASE8 = "$($r8.FINAL_VERDICT)/action=$($r8.ACTION)/changed=$($r8.CHANGED)"
$r8b = Invoke-Ensure
if ($r8.CHANGED -eq $true) { $failed++ }
if ($r8.FINAL_VERDICT -notin @("FRONTEND_DOWN_CONFIG_OK", "FRONTEND_DOWN")) { $failed++ }
if ($r8b.STOCK_SERVE_MAPPING_OK -ne $true) { $failed++ }

$stockHttp = 0
$lottoHttp = 0
try { $stockHttp = [int](Invoke-WebRequest -Uri "https://stock.tail3bf7b2.ts.net/mobile" -UseBasicParsing -TimeoutSec 20).StatusCode } catch { $stockHttp = 0 }
try { $lottoHttp = [int](Invoke-WebRequest -Uri "https://lottolab.tail3bf7b2.ts.net/" -UseBasicParsing -TimeoutSec 20).StatusCode } catch { $lottoHttp = 0 }
$results.STOCK_EXTERNAL = $stockHttp
$results.LOTTO_EXTERNAL = $lottoHttp

# 실제 실행 명령만 검사 (주석의 'serve reset 금지' 제외)
$hit = Select-String -Path @(
    (Join-Path $ProjectRoot "ops\ensure_stock_mobile_access.ps1"),
    (Join-Path $ProjectRoot "ops\dev\setup-tailscale-mobile-serve.ps1")
) -Pattern 'serve\s+reset' |
    Where-Object { $_.Line -match '&\s*\$|tailscale\.exe|Invoke-Ts' -and $_.Line -notmatch '금지|Abort|throw' }
$results.SERVE_RESET_COMMAND_PRESENT = [bool]@($hit).Count
$results.FAILED_COUNT = $failed
$results.FINAL = if ($failed -eq 0 -and $stockHttp -eq 200 -and $lottoHttp -eq 200 -and -not $results.SERVE_RESET_COMMAND_PRESENT) { "PASS" } else { "FAIL" }

$results | ConvertTo-Json -Depth 5
if ($results.FINAL -ne "PASS") { exit 1 }
exit 0
