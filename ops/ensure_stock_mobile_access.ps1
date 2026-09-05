#Requires -Version 5.1
<#
.SYNOPSIS
  Stock 모바일 Tailscale Serve idempotent ensure (svc:stock → :3000).
.DESCRIPTION
  JSON SoT 기반 drift 판정 + Stock-only repair.
  - Backend / LIVE / ARM / orders 일체 미변경
  - LottoLab classic/machine serve 미변경 (전후 fingerprint 비교)
  - Funnel 미사용 · serve reset 금지
  - Tailscale 미기동 시 bounded retry (startup self-heal)
  - Frontend :3000 DOWN이면 config 파괴 금지, health failure만 기록
.NOTES
  WRK-20260906-TAILSCALE-STOCK-SERVE-RECURRENCE-DURABLE-FIX-V1
#>
[CmdletBinding()]
param(
    [string]$ProjectRoot = "",
    [int]$FrontendPort = 3000,
    [string]$StockService = "svc:stock",
    [string]$StockHost = "stock.tail3bf7b2.ts.net",
    [string]$LottoHost = "lottolab.tail3bf7b2.ts.net",
    [string]$ProxyTarget = "http://127.0.0.1:3000",
    [string]$LottoProxyExpected = "http://127.0.0.1:8765",
    [switch]$SkipHttpProbe,
    [int]$TailscaleReadyRetries = 6,
    [int]$TailscaleReadyIntervalSec = 10
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

function Write-Step([string]$Message) {
    Write-Host "[ensure-stock-mobile] $Message"
}

function Get-TailscaleExe {
    foreach ($path in @(
            "C:\Program Files\Tailscale\tailscale.exe",
            "C:\Program Files (x86)\Tailscale\tailscale.exe"
        )) {
        if (Test-Path -LiteralPath $path) { return $path }
    }
    $cmd = Get-Command tailscale -ErrorAction SilentlyContinue
    if ($null -ne $cmd) { return $cmd.Source }
    return $null
}

function Test-PortListening([int]$Port) {
    try {
        $conn = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue |
            Select-Object -First 1
        return ($null -ne $conn)
    } catch {
        return $false
    }
}

function Test-HttpOk([string]$Url, [int]$TimeoutSec = 15) {
    try {
        $resp = Invoke-WebRequest -Uri $Url -UseBasicParsing -TimeoutSec $TimeoutSec
        return [int]$resp.StatusCode
    } catch {
        if ($_.Exception.Response -and $_.Exception.Response.StatusCode) {
            return [int]$_.Exception.Response.StatusCode.value__
        }
        return 0
    }
}

function Get-ServeStatusJson([string]$TsExe) {
    $raw = & $TsExe serve status --json 2>&1 | Out-String
    if ([string]::IsNullOrWhiteSpace($raw)) {
        return $null
    }
    try {
        return ($raw | ConvertFrom-Json)
    } catch {
        return $null
    }
}

function Get-ObjectProp($Obj, [string]$Name) {
    if ($null -eq $Obj) { return $null }
    $prop = $Obj.PSObject.Properties | Where-Object { $_.Name -eq $Name } | Select-Object -First 1
    if ($null -eq $prop) { return $null }
    return $prop.Value
}

function Get-LottoFingerprint($ServeJson, [string]$LottoHostName) {
    # StrictMode에서도 missing property로 throw 하지 않음
    if ($null -eq $ServeJson) { return "MISSING" }
    $key = "$LottoHostName`:443"
    $web = Get-ObjectProp $ServeJson "Web"
    if ($null -eq $web) { return "MISSING" }
    $node = Get-ObjectProp $web $key
    if ($null -eq $node) { return "MISSING" }
    $handlers = Get-ObjectProp $node "Handlers"
    $root = Get-ObjectProp $handlers "/"
    $proxy = Get-ObjectProp $root "Proxy"
    if ([string]::IsNullOrWhiteSpace([string]$proxy)) { return "MISSING" }
    return "HOST=$LottoHostName;PROXY=$proxy"
}

function Get-StockEndpointFromJson($ServeJson, [string]$ServiceName, [string]$StockHostName) {
    if ($null -eq $ServeJson) { return $null }
    $services = Get-ObjectProp $ServeJson "Services"
    if ($null -eq $services) { return $null }
    $svc = Get-ObjectProp $services $ServiceName
    if ($null -eq $svc) { return $null }
    $webKey = "$StockHostName`:443"
    $web = Get-ObjectProp $svc "Web"
    $node = Get-ObjectProp $web $webKey
    $handlers = Get-ObjectProp $node "Handlers"
    $root = Get-ObjectProp $handlers "/"
    $proxy = Get-ObjectProp $root "Proxy"
    if (-not [string]::IsNullOrWhiteSpace([string]$proxy)) { return [string]$proxy }
    return "PRESENT_NO_PROXY"
}

function Get-StockEndpointFromGetConfig([string]$TsExe, [string]$ServiceName) {
    $raw = & $TsExe serve get-config --all 2>&1 | Out-String
    if ([string]::IsNullOrWhiteSpace($raw)) { return $null }
    try {
        $cfg = $raw | ConvertFrom-Json
        $services = Get-ObjectProp $cfg "services"
        if ($null -eq $services) { return $null }
        $svc = Get-ObjectProp $services $ServiceName
        if ($null -eq $svc) { return $null }
        $endpoints = Get-ObjectProp $svc "endpoints"
        $ep = Get-ObjectProp $endpoints "tcp:443"
        if ([string]::IsNullOrWhiteSpace([string]$ep)) { return $null }
        return [string]$ep
    } catch {
        return $null
    }
}

if ([string]::IsNullOrWhiteSpace($ProjectRoot)) {
    $ProjectRoot = Split-Path -Parent $PSScriptRoot
    if ((Split-Path -Leaf $PSScriptRoot) -ieq "ops") {
        $ProjectRoot = Split-Path -Parent $PSScriptRoot
    }
}

# FrontendPort = localhost health probe 포트
# ProxyTarget = Serve mapping 기대값 (의도적으로 분리 — FE down 테스트 시 혼동 방지)

$runDir = Join-Path $ProjectRoot ".run"
New-Item -ItemType Directory -Force -Path $runDir | Out-Null
$logPath = Join-Path $runDir "ensure_stock_mobile_access.log"

$result = [ordered]@{
    timestamp_kst              = (Get-Date).ToString("o")
    event                      = "TAILSCALE_STOCK_SERVE_HEALTHY"
    FINAL_VERDICT              = "UNKNOWN"
    STOCK_SERVE_STATE          = "UNKNOWN"
    CHANGED                    = $false
    DRIFT                      = $false
    TAILSCALE_CONNECTED        = $false
    FRONTEND_3000              = $false
    STOCK_SERVICE_PRESENT      = $false
    STOCK_SERVE_MAPPING_OK     = $false
    STOCK_ENDPOINT             = $null
    LOTTO_SERVE_PRESENT        = $false
    LOTTO_FINGERPRINT_BEFORE   = $null
    LOTTO_FINGERPRINT_AFTER    = $null
    LOTTO_CONFIG_CHANGED       = $false
    ACTION                     = "NONE"
    STOCK_PUBLIC_HTTP          = $null
    LOTTO_PUBLIC_HTTP          = $null
    NOTES                      = @()
}

try {
    $ts = Get-TailscaleExe
    if (-not $ts) {
        throw "tailscale.exe not found"
    }

    $connected = $false
    for ($i = 1; $i -le [Math]::Max(1, $TailscaleReadyRetries); $i++) {
        $status = (& $ts status 2>&1 | Out-String)
        if ($status -match "(?i)Logged out|needs login|NoState|stopped") {
            $result.NOTES += "Tailscale not ready attempt=$i"
            Start-Sleep -Seconds ([Math]::Max(1, $TailscaleReadyIntervalSec))
            continue
        }
        $connected = $true
        break
    }
    if (-not $connected) {
        $result.FINAL_VERDICT = "TAILSCALE_NOT_CONNECTED"
        $result.event = "TAILSCALE_STOCK_SERVE_VERIFY_FAILED"
        $result.STOCK_SERVE_STATE = "TAILSCALE_UNAVAILABLE"
        throw "Tailscale not connected after retries"
    }
    $result.TAILSCALE_CONNECTED = $true

    $feOk = Test-PortListening -Port $FrontendPort
    $result.FRONTEND_3000 = $feOk

    $serveJson = Get-ServeStatusJson -TsExe $ts
    $lottoFpBefore = Get-LottoFingerprint -ServeJson $serveJson -LottoHostName $LottoHost
    $result.LOTTO_FINGERPRINT_BEFORE = $lottoFpBefore
    $result.LOTTO_SERVE_PRESENT = ($lottoFpBefore -ne "MISSING")

    $endpoint = Get-StockEndpointFromJson -ServeJson $serveJson -ServiceName $StockService -StockHostName $StockHost
    if ([string]::IsNullOrWhiteSpace($endpoint) -or $endpoint -eq "PRESENT_NO_PROXY") {
        $endpoint = Get-StockEndpointFromGetConfig -TsExe $ts -ServiceName $StockService
    }
    $result.STOCK_ENDPOINT = $endpoint
    $result.STOCK_SERVICE_PRESENT = -not [string]::IsNullOrWhiteSpace($endpoint)
    $mappingOk = ($endpoint -eq $ProxyTarget)
    $result.STOCK_SERVE_MAPPING_OK = [bool]$mappingOk
    $result.DRIFT = ($result.STOCK_SERVICE_PRESENT -and -not $mappingOk)

    if (-not $feOk) {
        # config 유지 · trading 무관 · 파괴 금지
        $result.NOTES += "Frontend :$FrontendPort DOWN — serve config not modified"
        $result.ACTION = "NONE"
        $result.CHANGED = $false
        if ($mappingOk) {
            $result.FINAL_VERDICT = "FRONTEND_DOWN_CONFIG_OK"
            $result.STOCK_SERVE_STATE = "CONFIG_OK_TARGET_DOWN"
            $result.event = "TAILSCALE_STOCK_SERVE_VERIFY_FAILED"
        } else {
            $result.FINAL_VERDICT = "FRONTEND_DOWN"
            $result.STOCK_SERVE_STATE = "MISSING_OR_DRIFT_TARGET_DOWN"
            $result.event = "TAILSCALE_STOCK_SERVE_VERIFY_FAILED"
        }
        throw "Frontend port $FrontendPort not listening"
    }

    if ($mappingOk) {
        $result.ACTION = "NONE"
        $result.CHANGED = $false
        $result.FINAL_VERDICT = "ALREADY_OK"
        $result.STOCK_SERVE_STATE = "HEALTHY"
        $result.event = "TAILSCALE_STOCK_SERVE_HEALTHY"
    } else {
        $why = if ($result.DRIFT) { "DRIFT" } else { "MISSING" }
        Write-Step "Repairing $StockService -> $ProxyTarget ($why; Lotto untouched; no reset)"
        $result.event = if ($result.DRIFT) { "TAILSCALE_STOCK_SERVE_DRIFT" } else { "TAILSCALE_STOCK_SERVE_REPAIRED" }
        $out = & $ts serve --bg --service=$StockService --https=443 $ProxyTarget 2>&1 | Out-String
        $result.NOTES += $out.Trim()
        # drained host면 advertise로 복구 (없어도 무해한 경우가 많음)
        $adv = & $ts serve advertise $StockService 2>&1 | Out-String
        if ($adv) { $result.NOTES += ("advertise: " + $adv.Trim()) }

        $serveJsonAfter = Get-ServeStatusJson -TsExe $ts
        $endpointAfter = Get-StockEndpointFromJson -ServeJson $serveJsonAfter -ServiceName $StockService -StockHostName $StockHost
        if ([string]::IsNullOrWhiteSpace($endpointAfter) -or $endpointAfter -eq "PRESENT_NO_PROXY") {
            $endpointAfter = Get-StockEndpointFromGetConfig -TsExe $ts -ServiceName $StockService
        }
        $result.STOCK_ENDPOINT = $endpointAfter
        $result.STOCK_SERVICE_PRESENT = -not [string]::IsNullOrWhiteSpace($endpointAfter)
        $result.STOCK_SERVE_MAPPING_OK = ($endpointAfter -eq $ProxyTarget)
        $result.ACTION = "RESTORE_SERVICE_MAPPING"
        $result.CHANGED = $true

        $lottoFpAfter = Get-LottoFingerprint -ServeJson $serveJsonAfter -LottoHostName $LottoHost
        $result.LOTTO_FINGERPRINT_AFTER = $lottoFpAfter
        $result.LOTTO_SERVE_PRESENT = ($lottoFpAfter -ne "MISSING")
        $result.LOTTO_CONFIG_CHANGED = ($lottoFpBefore -ne $lottoFpAfter)

        if (-not $result.STOCK_SERVE_MAPPING_OK) {
            $result.FINAL_VERDICT = "SERVE_RESTORE_INCOMPLETE"
            $result.STOCK_SERVE_STATE = "REPAIR_FAILED"
            $result.event = "TAILSCALE_STOCK_SERVE_VERIFY_FAILED"
            throw "Serve restore did not reach expected endpoint $ProxyTarget (got=$endpointAfter)"
        }
        if ($result.LOTTO_CONFIG_CHANGED) {
            $result.FINAL_VERDICT = "LOTTO_CONFIG_CHANGED"
            $result.STOCK_SERVE_STATE = "REPAIRED_BUT_LOTTO_DRIFT"
            $result.event = "TAILSCALE_STOCK_SERVE_VERIFY_FAILED"
            throw "Lotto serve fingerprint changed unexpectedly"
        }
        if (-not $result.LOTTO_SERVE_PRESENT) {
            $result.FINAL_VERDICT = "LOTTO_SERVE_MISSING_AFTER"
            throw "LottoLab serve missing after stock restore"
        }
        $result.FINAL_VERDICT = "RESTORED"
        $result.STOCK_SERVE_STATE = "REPAIRED"
        $result.event = "TAILSCALE_STOCK_SERVE_REPAIRED"
    }

    if ([string]::IsNullOrWhiteSpace([string]$result.LOTTO_FINGERPRINT_AFTER)) {
        $serveJsonEnd = Get-ServeStatusJson -TsExe $ts
        $result.LOTTO_FINGERPRINT_AFTER = Get-LottoFingerprint -ServeJson $serveJsonEnd -LottoHostName $LottoHost
        $result.LOTTO_CONFIG_CHANGED = ($result.LOTTO_FINGERPRINT_BEFORE -ne $result.LOTTO_FINGERPRINT_AFTER)
    }

    if (-not $SkipHttpProbe) {
        $result.STOCK_PUBLIC_HTTP = Test-HttpOk "https://$StockHost/login"
        $result.LOTTO_PUBLIC_HTTP = Test-HttpOk "https://$LottoHost/"
    }

    if ($result.FINAL_VERDICT -eq "UNKNOWN") {
        $result.FINAL_VERDICT = "OK"
    }
} catch {
    $result.NOTES += $_.Exception.Message
    if ($result.FINAL_VERDICT -eq "UNKNOWN") {
        $result.FINAL_VERDICT = "FAILED"
        $result.event = "TAILSCALE_STOCK_SERVE_VERIFY_FAILED"
    }
}

$line = ($result | ConvertTo-Json -Compress -Depth 8)
Add-Content -LiteralPath $logPath -Encoding UTF8 -Value $line
Write-Step ($result | ConvertTo-Json -Depth 8)

# trading cascade 금지 — 항상 exit 0
exit 0
