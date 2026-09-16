#Requires -Version 5.1
<#
.SYNOPSIS
  Stock 모바일 Tailscale Serve idempotent ensure (svc:stock → :3000).
.DESCRIPTION
  JSON SoT 기반 drift 판정 + Stock-only repair + HTTPS postcondition fail-closed.
  - Backend / LIVE / ARM / orders 일체 미변경
  - LottoLab classic/machine serve 미변경 (전후 fingerprint 비교)
  - Funnel 미사용 · serve reset 금지
  - Frontend readiness bounded wait (재부팅 ordering)
  - 성공 = mapping OK + (기본) HTTPS reachable — CLI exit code만으로 PASS 금지
  - 실패 시 non-zero exit (Task LastTaskResult 반영)
.NOTES
  WRK-20260906-STOCK-TAILSCALE-SERVE-POSTCONDITION-V2
  Parent: WRK-20260906-TAILSCALE-STOCK-SERVE-RECURRENCE-DURABLE-FIX-V1
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
    [int]$TailscaleReadyIntervalSec = 10,
    [int]$FrontendReadyRetries = 12,
    [int]$FrontendReadyIntervalSec = 10,
    [int]$ServeReadyRetries = 6,
    [int]$ServeReadyIntervalSec = 5
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

function Test-LocalFrontendReady([int]$Port, [int]$TimeoutSec = 3) {
    if (-not (Test-PortListening -Port $Port)) { return $false }
    try {
        $resp = Invoke-WebRequest -Uri "http://127.0.0.1:$Port/" -UseBasicParsing -TimeoutSec $TimeoutSec
        $code = [int]$resp.StatusCode
        return ($code -ge 200 -and $code -lt 500)
    } catch {
        # LISTEN만 있고 HTTP 아직 준비 전일 수 있음
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
        # connection refused / timeout → 0
        return 0
    }
}

function Test-HttpReachableCode([int]$Code) {
    return ($Code -ge 200 -and $Code -lt 400)
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

function Get-StockEndpointFromStatusJson($ServeJson, [string]$ServiceName, [string]$StockHostName) {
    # Runtime SoT: serve status --json (Services). get-config alone는 HEALTHY로 쓰지 않음.
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

function Get-StockMappingState([string]$TsExe, [string]$ServiceName, [string]$StockHostName, [string]$ExpectedProxy) {
    $serveJson = Get-ServeStatusJson -TsExe $TsExe
    $endpoint = Get-StockEndpointFromStatusJson -ServeJson $serveJson -ServiceName $ServiceName -StockHostName $StockHostName
    $fromStatus = -not [string]::IsNullOrWhiteSpace($endpoint)
    $cfgHint = Get-StockEndpointFromGetConfig -TsExe $TsExe -ServiceName $ServiceName
    $mappingOk = ($endpoint -eq $ExpectedProxy)
    return [pscustomobject]@{
        ServeJson     = $serveJson
        Endpoint      = $endpoint
        ConfigHint    = $cfgHint
        PresentStatus = $fromStatus
        MappingOk     = [bool]$mappingOk
    }
}

function Invoke-StockServeRepair([string]$TsExe, [string]$ServiceName, [string]$Proxy) {
    # svc:stock만 대상. reset/clear all/Funnel/hostname 금지.
    $out = & $TsExe serve --service=$ServiceName --bg --https=443 $Proxy 2>&1 | Out-String
    $adv = & $TsExe serve advertise $ServiceName 2>&1 | Out-String
    return @{
        ServeOut      = $out.Trim()
        AdvertiseOut  = $(if ($adv) { $adv.Trim() } else { "" })
    }
}

if ([string]::IsNullOrWhiteSpace($ProjectRoot)) {
    $ProjectRoot = Split-Path -Parent $PSScriptRoot
    if ((Split-Path -Leaf $PSScriptRoot) -ieq "ops") {
        $ProjectRoot = Split-Path -Parent $PSScriptRoot
    }
}

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
    STOCK_CONFIG_HINT          = $null
    LOTTO_SERVE_PRESENT        = $false
    LOTTO_FINGERPRINT_BEFORE   = $null
    LOTTO_FINGERPRINT_AFTER    = $null
    LOTTO_CONFIG_CHANGED       = $false
    ACTION                     = "NONE"
    STOCK_PUBLIC_HTTP          = $null
    STOCK_HTTPS_OK             = $false
    LOTTO_PUBLIC_HTTP          = $null
    POSTCONDITION_OK           = $false
    EXIT_CODE                  = 1
    NOTES                      = @()
}

$scriptExit = 1

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

    # 재부팅: Frontend task가 뒤에 올 수 있음 → bounded wait
    $feOk = $false
    for ($i = 1; $i -le [Math]::Max(1, $FrontendReadyRetries); $i++) {
        if (Test-LocalFrontendReady -Port $FrontendPort) {
            $feOk = $true
            break
        }
        $result.NOTES += "Frontend :$FrontendPort not ready attempt=$i/$FrontendReadyRetries"
        if ($i -lt $FrontendReadyRetries) {
            Start-Sleep -Seconds ([Math]::Max(1, $FrontendReadyIntervalSec))
        }
    }
    $result.FRONTEND_3000 = $feOk

    $map0 = Get-StockMappingState -TsExe $ts -ServiceName $StockService -StockHostName $StockHost -ExpectedProxy $ProxyTarget
    $lottoFpBefore = Get-LottoFingerprint -ServeJson $map0.ServeJson -LottoHostName $LottoHost
    $result.LOTTO_FINGERPRINT_BEFORE = $lottoFpBefore
    $result.LOTTO_SERVE_PRESENT = ($lottoFpBefore -ne "MISSING")
    $result.STOCK_ENDPOINT = $map0.Endpoint
    $result.STOCK_CONFIG_HINT = $map0.ConfigHint
    $result.STOCK_SERVICE_PRESENT = [bool]$map0.PresentStatus
    $result.STOCK_SERVE_MAPPING_OK = [bool]$map0.MappingOk
    $result.DRIFT = ($map0.PresentStatus -and -not $map0.MappingOk)

    if (-not $feOk) {
        # config 파괴 금지. 단 Task는 실패로 남겨 재시도/가시성 확보 (H139: 이전엔 exit 0 → 위장 PASS)
        $result.NOTES += "Frontend :$FrontendPort DOWN after bounded wait — serve config not modified"
        $result.ACTION = "NONE"
        $result.CHANGED = $false
        if ($map0.MappingOk) {
            $result.FINAL_VERDICT = "FRONTEND_DOWN_CONFIG_OK"
            $result.STOCK_SERVE_STATE = "CONFIG_OK_TARGET_DOWN"
        } else {
            $result.FINAL_VERDICT = "FRONTEND_DOWN"
            $result.STOCK_SERVE_STATE = "MISSING_OR_DRIFT_TARGET_DOWN"
        }
        $result.event = "TAILSCALE_STOCK_SERVE_VERIFY_FAILED"
        throw "Frontend port $FrontendPort not ready after bounded wait"
    }

    if ($map0.MappingOk) {
        $result.ACTION = "NONE"
        $result.CHANGED = $false
        $result.FINAL_VERDICT = "ALREADY_HEALTHY"
        $result.STOCK_SERVE_STATE = "HEALTHY"
        $result.event = "TAILSCALE_STOCK_SERVE_HEALTHY"
    } else {
        $why = if ($result.DRIFT) { "DRIFT" } else { "MISSING" }
        Write-Step "Repairing $StockService -> $ProxyTarget ($why; Lotto untouched; no reset)"
        $result.event = if ($result.DRIFT) { "TAILSCALE_STOCK_SERVE_DRIFT" } else { "TAILSCALE_STOCK_SERVE_REPAIRED" }
        $repair = Invoke-StockServeRepair -TsExe $ts -ServiceName $StockService -Proxy $ProxyTarget
        if ($repair.ServeOut) { $result.NOTES += $repair.ServeOut }
        if ($repair.AdvertiseOut) { $result.NOTES += ("advertise: " + $repair.AdvertiseOut) }
        $result.ACTION = "RESTORE_SERVICE_MAPPING"
        $result.CHANGED = $true

        $mapOkAfter = $false
        $endpointAfter = $null
        $serveJsonAfter = $null
        for ($i = 1; $i -le [Math]::Max(1, $ServeReadyRetries); $i++) {
            $mapN = Get-StockMappingState -TsExe $ts -ServiceName $StockService -StockHostName $StockHost -ExpectedProxy $ProxyTarget
            $serveJsonAfter = $mapN.ServeJson
            $endpointAfter = $mapN.Endpoint
            if ($mapN.MappingOk) {
                $mapOkAfter = $true
                break
            }
            $result.NOTES += "Serve mapping not ready attempt=$i got=$endpointAfter"
            Start-Sleep -Seconds ([Math]::Max(1, $ServeReadyIntervalSec))
        }

        $result.STOCK_ENDPOINT = $endpointAfter
        $result.STOCK_SERVICE_PRESENT = -not [string]::IsNullOrWhiteSpace([string]$endpointAfter)
        $result.STOCK_SERVE_MAPPING_OK = [bool]$mapOkAfter

        $lottoFpAfter = Get-LottoFingerprint -ServeJson $serveJsonAfter -LottoHostName $LottoHost
        $result.LOTTO_FINGERPRINT_AFTER = $lottoFpAfter
        $result.LOTTO_SERVE_PRESENT = ($lottoFpAfter -ne "MISSING")
        $result.LOTTO_CONFIG_CHANGED = ($lottoFpBefore -ne $lottoFpAfter)

        if (-not $mapOkAfter) {
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
        if ($result.LOTTO_CONFIG_CHANGED) {
            $result.FINAL_VERDICT = "LOTTO_CONFIG_CHANGED"
            $result.event = "TAILSCALE_STOCK_SERVE_VERIFY_FAILED"
            throw "Lotto serve fingerprint changed unexpectedly"
        }
    }

    # Postcondition: HTTPS must be reachable unless explicitly skipped (unit/offline)
    if (-not $SkipHttpProbe) {
        $httpsOk = $false
        $stockCode = 0
        for ($i = 1; $i -le [Math]::Max(1, $ServeReadyRetries); $i++) {
            # /login 또는 / — connection refused 가 아니면 2xx/3xx
            $stockCode = Test-HttpOk "https://$StockHost/"
            if (-not (Test-HttpReachableCode $stockCode)) {
                $stockCode = Test-HttpOk "https://$StockHost/login"
            }
            if (Test-HttpReachableCode $stockCode) {
                $httpsOk = $true
                break
            }
            $result.NOTES += "Stock HTTPS not reachable attempt=$i code=$stockCode"
            Start-Sleep -Seconds ([Math]::Max(1, $ServeReadyIntervalSec))
        }
        $result.STOCK_PUBLIC_HTTP = $stockCode
        $result.STOCK_HTTPS_OK = [bool]$httpsOk
        $result.LOTTO_PUBLIC_HTTP = Test-HttpOk "https://$LottoHost/"

        if (-not $httpsOk) {
            $result.FINAL_VERDICT = "HTTPS_POSTCONDITION_FAILED"
            $result.STOCK_SERVE_STATE = "MAPPING_OK_HTTPS_FAIL"
            $result.event = "TAILSCALE_STOCK_SERVE_VERIFY_FAILED"
            throw "Stock HTTPS postcondition failed for https://$StockHost/ (code=$stockCode)"
        }
    } else {
        $result.NOTES += "SkipHttpProbe=true — HTTPS postcondition skipped"
        $result.STOCK_HTTPS_OK = $null
    }

    # 최종 postcondition 묶음
    $result.POSTCONDITION_OK = (
        [bool]$result.FRONTEND_3000 -and
        [bool]$result.STOCK_SERVE_MAPPING_OK -and
        ($SkipHttpProbe -or [bool]$result.STOCK_HTTPS_OK) -and
        -not [bool]$result.LOTTO_CONFIG_CHANGED
    )
    if (-not $result.POSTCONDITION_OK) {
        $result.FINAL_VERDICT = "POSTCONDITION_FAILED"
        $result.event = "TAILSCALE_STOCK_SERVE_VERIFY_FAILED"
        throw "Postcondition bundle failed"
    }

    if ($result.FINAL_VERDICT -eq "UNKNOWN") {
        $result.FINAL_VERDICT = "OK"
    }
    $scriptExit = 0
    $result.EXIT_CODE = 0
} catch {
    $result.NOTES += $_.Exception.Message
    if ($result.FINAL_VERDICT -eq "UNKNOWN") {
        $result.FINAL_VERDICT = "FAILED"
        $result.event = "TAILSCALE_STOCK_SERVE_VERIFY_FAILED"
    }
    $scriptExit = 1
    $result.EXIT_CODE = 1
}

$line = ($result | ConvertTo-Json -Compress -Depth 8)
Add-Content -LiteralPath $logPath -Encoding UTF8 -Value $line
Write-Step ($result | ConvertTo-Json -Depth 8)

# Task Scheduler가 실패를 정확히 반영하도록 non-zero exit
exit $scriptExit
