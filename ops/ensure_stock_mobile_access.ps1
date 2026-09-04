#Requires -Version 5.1
<#
.SYNOPSIS
  Stock 모바일 Tailscale Serve idempotent ensure (svc:stock → :3000).
.DESCRIPTION
  - Backend / LIVE / ARM / orders 일체 미변경
  - LottoLab classic serve 미변경
  - Funnel 미사용 · serve reset 금지
  - 이미 정상이면 NO_CHANGE
.NOTES
  WRK-20260904-STOCK-MOBILE-TAILSCALE-SERVE-STARTUP-SELF-HEAL-V1
#>
[CmdletBinding()]
param(
    [string]$ProjectRoot = "",
    [int]$FrontendPort = 3000,
    [string]$StockService = "svc:stock",
    [string]$StockHost = "stock.tail3bf7b2.ts.net",
    [string]$LottoHost = "lottolab.tail3bf7b2.ts.net",
    [string]$ProxyTarget = "http://127.0.0.1:3000",
    [switch]$SkipHttpProbe
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
        # some SPA return 200/307/404 still reachable
        if ($_.Exception.Response -and $_.Exception.Response.StatusCode) {
            return [int]$_.Exception.Response.StatusCode.value__
        }
        return 0
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
    timestamp_kst           = (Get-Date).ToString("o")
    FINAL_VERDICT           = "UNKNOWN"
    CHANGED                 = $false
    TAILSCALE_CONNECTED     = $false
    FRONTEND_3000           = $false
    STOCK_SERVICE_PRESENT   = $false
    STOCK_SERVE_MAPPING_OK  = $false
    LOTTO_SERVE_PRESENT     = $false
    ACTION                  = "NONE"
    STOCK_PUBLIC_HTTP       = $null
    LOTTO_PUBLIC_HTTP       = $null
    NOTES                   = @()
}

try {
    $ts = Get-TailscaleExe
    if (-not $ts) {
        throw "tailscale.exe not found"
    }

    $status = (& $ts status 2>&1 | Out-String)
    if ($status -match "(?i)Logged out|needs login|NoState") {
        $result.NOTES += "Tailscale not connected/logged in"
        $result.FINAL_VERDICT = "TAILSCALE_NOT_CONNECTED"
        throw "Tailscale not connected"
    }
    $result.TAILSCALE_CONNECTED = $true

    $feOk = Test-PortListening -Port $FrontendPort
    $result.FRONTEND_3000 = $feOk
    if (-not $feOk) {
        $result.NOTES += "Frontend :$FrontendPort DOWN — start production frontend separately; this script does not start trading backend"
        $result.FINAL_VERDICT = "FRONTEND_DOWN"
        # do not attempt serve map without local target
        throw "Frontend port $FrontendPort not listening"
    }

    $serveBefore = (& $ts serve status 2>&1 | Out-String)
    $result.LOTTO_SERVE_PRESENT = ($serveBefore -match [regex]::Escape($LottoHost))
    $result.STOCK_SERVICE_PRESENT = ($serveBefore -match [regex]::Escape($StockHost) -or $serveBefore -match [regex]::Escape($StockService))
    $mappingOk = (
        $serveBefore -match [regex]::Escape($StockHost) -and
        $serveBefore -match [regex]::Escape($ProxyTarget.Replace("http://", ""))
    ) -or (
        $serveBefore -match "svc:stock" -and
        $serveBefore -match "127\.0\.0\.1:$FrontendPort"
    )
    $result.STOCK_SERVE_MAPPING_OK = [bool]$mappingOk

    if ($mappingOk) {
        $result.ACTION = "NO_CHANGE"
        $result.CHANGED = $false
        $result.FINAL_VERDICT = "ALREADY_OK"
    } else {
        Write-Step "Restoring $StockService -> $ProxyTarget (Lotto untouched, no reset)"
        # Canonical command (History #61 / prior recovery)
        $out = & $ts serve --bg --service=$StockService --https=443 $ProxyTarget 2>&1 | Out-String
        $result.NOTES += $out.Trim()
        $result.ACTION = "RESTORED_STOCK_SERVE"
        $result.CHANGED = $true

        $serveAfter = (& $ts serve status 2>&1 | Out-String)
        $result.LOTTO_SERVE_PRESENT = ($serveAfter -match [regex]::Escape($LottoHost))
        $result.STOCK_SERVICE_PRESENT = ($serveAfter -match [regex]::Escape($StockHost) -or $serveAfter -match "svc:stock")
        $result.STOCK_SERVE_MAPPING_OK = (
            $serveAfter -match [regex]::Escape($StockHost) -and
            $serveAfter -match "127\.0\.0\.1:$FrontendPort"
        )
        if (-not $result.STOCK_SERVE_MAPPING_OK) {
            $result.FINAL_VERDICT = "SERVE_RESTORE_INCOMPLETE"
            throw "Serve restore did not show expected mapping"
        }
        if (-not $result.LOTTO_SERVE_PRESENT) {
            $result.FINAL_VERDICT = "LOTTO_SERVE_MISSING_AFTER"
            throw "LottoLab serve missing after stock restore — unexpected"
        }
        $result.FINAL_VERDICT = "RESTORED"
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
    }
}

$line = ($result | ConvertTo-Json -Compress -Depth 6)
Add-Content -LiteralPath $logPath -Encoding UTF8 -Value $line
Write-Step ($result | ConvertTo-Json -Depth 6)

# exit 0 even on FRONTEND_DOWN so startup chain does not cascade into trading restart
exit 0
