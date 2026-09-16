#Requires -Version 5.1
<#
.SYNOPSIS
  Stock Tailscale Serve ensure — postcondition + fail-closed test matrix.
.NOTES
  WRK-20260906-STOCK-TAILSCALE-SERVE-POSTCONDITION-V2
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
    $code = $LASTEXITCODE
    $ErrorActionPreference = $prev
    $m = [regex]::Matches($out, '(?s)\{[^{}]*"FINAL_VERDICT"[^{}]*\}')
    if ($m.Count -eq 0) { throw "ensure produced no JSON (exit=$code): $out" }
    $obj = ($m[$m.Count - 1].Value | ConvertFrom-Json)
    return [pscustomobject]@{
        Json     = $obj
        ExitCode = [int]$code
        Raw      = $out
    }
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

function Get-StockEndpoint {
    $prev = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    $j = & $ts serve status --json 2>&1 | Out-String | ConvertFrom-Json
    $ErrorActionPreference = $prev
    try {
        return [string]$j.Services."svc:stock".Web."stock.tail3bf7b2.ts.net:443".Handlers."/".Proxy
    } catch {
        return $null
    }
}

function Invoke-TsSafe([string[]]$TsArgs) {
    $prev = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    & $ts @TsArgs 2>&1 | Out-String | Out-Null
    $ErrorActionPreference = $prev
}

function Assert-Pass([bool]$Cond, [string]$Name, $results) {
    if ($Cond) {
        Write-Host "PASS $Name"
        $results[$Name] = "PASS"
    } else {
        Write-Host "FAIL $Name"
        $results[$Name] = "FAIL"
        $script:failed++
    }
}

$results = [ordered]@{}
$script:failed = 0

# Baseline heal
$null = Invoke-Ensure
if (-not (Get-StockPresent)) { $null = Invoke-Ensure }

Write-Host "=== A absent self-heal ==="
$lottoBeforeA = Get-LottoFp
Invoke-TsSafe @("serve", "clear", "svc:stock")
Start-Sleep -Seconds 2
$missing = -not (Get-StockPresent)
$rA = Invoke-Ensure
Assert-Pass ($missing -and $rA.ExitCode -eq 0 -and $rA.Json.FINAL_VERDICT -eq "RESTORED" -and (Get-StockPresent)) "A_absent_self_heal" $results
Assert-Pass ($lottoBeforeA -eq (Get-LottoFp)) "A_lotto_unchanged" $results
Assert-Pass ([int]$rA.Json.STOCK_PUBLIC_HTTP -ge 200 -and [int]$rA.Json.STOCK_PUBLIC_HTTP -lt 400) "A_https_reachable" $results

Write-Host "=== B already healthy ==="
$rB = Invoke-Ensure
Assert-Pass ($rB.ExitCode -eq 0 -and $rB.Json.FINAL_VERDICT -eq "ALREADY_HEALTHY" -and $rB.Json.CHANGED -eq $false) "B_already_healthy" $results

Write-Host "=== C wrong mapping repair ==="
Invoke-TsSafe @("serve", "--bg", "--service=svc:stock", "--https=443", "http://127.0.0.1:3999")
Start-Sleep -Seconds 2
$rC = Invoke-Ensure
Assert-Pass ($rC.ExitCode -eq 0 -and $rC.Json.FINAL_VERDICT -eq "RESTORED" -and (Get-StockEndpoint) -eq "http://127.0.0.1:3000") "C_wrong_mapping_repair" $results

Write-Host "=== D frontend unavailable fail-closed ==="
$rD = Invoke-Ensure -ExtraArgs @(
    "-FrontendPort", "39998",
    "-FrontendReadyRetries", "1",
    "-FrontendReadyIntervalSec", "1",
    "-SkipHttpProbe"
)
Assert-Pass ($rD.ExitCode -ne 0 -and $rD.Json.FINAL_VERDICT -in @("FRONTEND_DOWN", "FRONTEND_DOWN_CONFIG_OK")) "D_frontend_unavailable_nonzero" $results
Assert-Pass ($rD.Json.CHANGED -eq $false) "D_no_mutation_on_fe_down" $results
# restore health after D
$rDfix = Invoke-Ensure
Assert-Pass ($rDfix.ExitCode -eq 0 -and $rDfix.Json.STOCK_SERVE_MAPPING_OK -eq $true) "D_restore_after" $results

Write-Host "=== E lotto unchanged ==="
$lp = Get-LottoFp
Assert-Pass ($lp -eq "http://127.0.0.1:8765") "E_lotto_mapping" $results

Write-Host "=== F 2nd invoke idempotent ==="
$before = (& $ts serve status --json 2>&1 | Out-String).Trim()
$rF1 = Invoke-Ensure -ExtraArgs @("-SkipHttpProbe")
$rF2 = Invoke-Ensure -ExtraArgs @("-SkipHttpProbe")
$after = (& $ts serve status --json 2>&1 | Out-String).Trim()
Assert-Pass ($rF1.ExitCode -eq 0 -and $rF2.ExitCode -eq 0 -and $rF1.Json.CHANGED -eq $false -and $rF2.Json.CHANGED -eq $false) "F_idempotent_exit0" $results
Assert-Pass ($before -eq $after) "F_config_unchanged" $results

Write-Host "=== G no destructive commands ==="
$src = Get-Content -LiteralPath $ensure -Raw
Assert-Pass ($src -notmatch '(?m)^\s*&\s*\$\w+\s+serve\s+reset\b') "G_no_serve_reset" $results
Assert-Pass ($src -notmatch '(?i)tailscale\s+funnel|&\s*\$\w+[^\r\n]*funnel') "G_no_funnel" $results
Assert-Pass ($src -notmatch '(?i)(?:tailscale\s+set|--hostname|&\s*\$\w+[^\r\n]*set-hostname)') "G_no_hostname_mutation" $results
Assert-Pass ($src -match 'exit\s+\$scriptExit') "G_nonzero_exit_path" $results
Assert-Pass ($src -notmatch '(?m)^\s*exit\s+0\s*$') "G_no_always_exit_zero" $results

# External HTTP smoke
$stockHttp = 0
$lottoHttp = 0
$cbHttp = 0
try { $stockHttp = [int](Invoke-WebRequest -Uri "https://stock.tail3bf7b2.ts.net/" -UseBasicParsing -TimeoutSec 20).StatusCode } catch {
    if ($_.Exception.Response) { $stockHttp = [int]$_.Exception.Response.StatusCode.value__ } else { $stockHttp = 0 }
}
try {
    $cb = Invoke-WebRequest -Uri "https://stock.tail3bf7b2.ts.net/api/auth/callback/google" -UseBasicParsing -TimeoutSec 20
    $cbHttp = [int]$cb.StatusCode
} catch {
    if ($_.Exception.Response) { $cbHttp = [int]$_.Exception.Response.StatusCode.value__ } else { $cbHttp = 0 }
}
try { $lottoHttp = [int](Invoke-WebRequest -Uri "https://lottolab.tail3bf7b2.ts.net/" -UseBasicParsing -TimeoutSec 20).StatusCode } catch { $lottoHttp = 0 }

Assert-Pass ($stockHttp -ge 200 -and $stockHttp -lt 400) "STOCK_HTTPS_SMOKE" $results
Assert-Pass ($cbHttp -gt 0) "GOOGLE_CALLBACK_HTTP_NOT_REFUSED" $results
Assert-Pass ($lottoHttp -eq 200) "LOTTO_HTTPS_SMOKE" $results

# Ports untouched (informational asserts)
$port3 = @(Get-NetTCPConnection -LocalPort 3000 -State Listen -ErrorAction SilentlyContinue).Count
$port8 = @(Get-NetTCPConnection -LocalPort 8000 -State Listen -ErrorAction SilentlyContinue).Count
Assert-Pass ($port3 -ge 1) "FRONTEND_STILL_LISTENING" $results
Assert-Pass ($port8 -ge 1) "BACKEND_STILL_LISTENING" $results

$results.FAILED_COUNT = $script:failed
$results.STOCK_EXTERNAL = $stockHttp
$results.CALLBACK_HTTP = $cbHttp
$results.LOTTO_EXTERNAL = $lottoHttp
$results.FINAL = if ($script:failed -eq 0) { "PASS" } else { "FAIL" }
$results | ConvertTo-Json -Depth 5
if ($results.FINAL -ne "PASS") { exit 1 }
exit 0
