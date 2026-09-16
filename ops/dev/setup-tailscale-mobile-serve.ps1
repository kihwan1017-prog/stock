#Requires -Version 5.1
<#
.SYNOPSIS
  Tailscale 설치 확인 + 로그인 상태 + Serve(HTTPS, Tailnet only) 설정
.DESCRIPTION
  - Funnel 사용 금지 (공개 인터넷 노출 금지)
  - Frontend 127.0.0.1:3000 만 Serve
  - Backend/DB/Ollama 직접 Serve 금지
  - 관리자 로그인 우회 없음 (앱 인증 유지)
.NOTES
  관리자 PowerShell에서 실행 권장 (설치/서비스).
#>
[CmdletBinding()]
param(
    [string]$ProjectRoot = "",
    [int]$FrontendPort = 3000,
    [string]$MsiPath = "",
    [switch]$InstallOnly,
    [switch]$SkipInstall
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

function Write-Step([string]$Message) {
    Write-Host "[tailscale-mobile] $Message"
}

function Resolve-ProjectRoot {
    if (-not [string]::IsNullOrWhiteSpace($ProjectRoot)) {
        return (Resolve-Path -LiteralPath $ProjectRoot).Path
    }
    # ops/dev -> repo root
    return (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot "..\..")).Path
}

function Get-TailscaleExe {
    $candidates = @(
        "C:\Program Files\Tailscale\tailscale.exe",
        "C:\Program Files (x86)\Tailscale\tailscale.exe"
    )
    foreach ($path in $candidates) {
        if (Test-Path -LiteralPath $path) { return $path }
    }
    $cmd = Get-Command tailscale -ErrorAction SilentlyContinue
    if ($null -ne $cmd) { return $cmd.Source }
    return $null
}

function Invoke-Ts {
    param(
        [Parameter(Mandatory = $true)][string]$Exe,
        [Parameter(Mandatory = $true)][string[]]$Args
    )
    & $Exe @Args 2>&1
}

$root = Resolve-ProjectRoot
$runDir = Join-Path $root ".run"
New-Item -ItemType Directory -Force -Path $runDir | Out-Null

Write-Step "ProjectRoot=$root"

$ts = Get-TailscaleExe
if (-not $ts -and -not $SkipInstall) {
    Write-Step "Tailscale not installed. Starting MSI install (UAC approve required)."
    if ([string]::IsNullOrWhiteSpace($MsiPath)) {
        $MsiPath = Join-Path $runDir "tailscale-setup-1.102.3-amd64.msi"
    }
    if (-not (Test-Path -LiteralPath $MsiPath)) {
        Write-Step "MSI missing. winget install..."
        winget install --id Tailscale.Tailscale --exact --architecture x64 `
            --accept-package-agreements --accept-source-agreements --disable-interactivity
    } else {
        $p = Start-Process -FilePath "msiexec.exe" `
            -ArgumentList @("/i", $MsiPath, "/passive", "/norestart") `
            -Verb RunAs -PassThru -Wait
        Write-Step "msiexec exit=$($p.ExitCode)"
        if ($p.ExitCode -ne 0 -and $p.ExitCode -ne 3010) {
            throw "Tailscale MSI install failed: exit=$($p.ExitCode)"
        }
    }
    Start-Sleep -Seconds 3
    $ts = Get-TailscaleExe
}

if (-not $ts) {
    throw "tailscale.exe not found. Install Tailscale Windows client, then re-run."
}

Write-Step "EXE=$ts"
$version = (Invoke-Ts -Exe $ts -Args @("version") | Out-String).Trim()
Write-Step "VERSION:`n$version"

$svc = Get-Service -Name "Tailscale" -ErrorAction SilentlyContinue
if ($null -eq $svc) {
    $svc = Get-Service -Name "*Tailscale*" -ErrorAction SilentlyContinue | Select-Object -First 1
}
if ($null -ne $svc) {
    Write-Step "SERVICE name=$($svc.Name) status=$($svc.Status) start=$($svc.StartType)"
    if ($svc.Status -ne "Running") {
        try { Start-Service -Name $svc.Name } catch {
            Write-Step "Start-Service failed (may need admin): $($_.Exception.Message)"
        }
    }
}

$statusRaw = (Invoke-Ts -Exe $ts -Args @("status", "--json") | Out-String)
$loggedIn = $true
if ($statusRaw -match "Logged out" -or $statusRaw -match "needs login" -or $statusRaw -match '"BackendState"\s*:\s*"NeedsLogin"') {
    $loggedIn = $false
}

# status --json may fail when logged out; also try plain status
$plainStatus = (Invoke-Ts -Exe $ts -Args @("status") | Out-String)
if ($plainStatus -match "Logged out" -or $plainStatus -match "log in") {
    $loggedIn = $false
}

if (-not $loggedIn) {
    Write-Step "NOT LOGGED IN. Starting browser auth (do not share credentials with agents)."
    Write-Host ""
    Write-Host "=== USER ACTION ===" -ForegroundColor Yellow
    Write-Host "1) Browser opens -> Tailscale account login"
    Write-Host "2) Approve this device (kikicom)"
    Write-Host "3) Phone: install Tailscale app, same account, Tailscale ON"
    Write-Host "4) Re-run this script after login"
    Write-Host "===================" -ForegroundColor Yellow
    Write-Host ""
    Invoke-Ts -Exe $ts -Args @("login") | Out-Host
    $evidence = [ordered]@{
        FINAL_VERDICT = "TAILSCALE_MOBILE_SETUP_USER_ACTION_REQUIRED"
        INSTALLED     = $true
        LOGGED_IN     = $false
        NEXT_ACTION   = "COMPLETE_TAILSCALE_LOGIN_THEN_RERUN"
        TIMESTAMP_UTC = (Get-Date).ToUniversalTime().ToString("o")
    }
    ($evidence | ConvertTo-Json -Depth 6) | Set-Content -Encoding UTF8 (Join-Path $runDir "k_tailscale_mobile_https_setup.json")
    exit 2
}

if ($InstallOnly) {
    Write-Step "InstallOnly: login OK, skip Serve."
    exit 0
}

# Funnel must stay OFF
Write-Step "Checking Funnel (must be OFF)..."
$funnelStatus = (Invoke-Ts -Exe $ts -Args @("funnel", "status") | Out-String)
if ($funnelStatus -match "(?i)https://|Funnel on|Enabled:\s*true") {
    throw "Funnel appears enabled. Aborting. Run: tailscale funnel reset / funnel off"
}

# Frontend must listen locally
$frontendListening = $false
try {
    $conn = Get-NetTCPConnection -LocalPort $FrontendPort -State Listen -ErrorAction SilentlyContinue |
        Select-Object -First 1
    if ($null -ne $conn) { $frontendListening = $true }
} catch { }
if (-not $frontendListening) {
    throw "Frontend port $FrontendPort is not listening. Start Next.js first."
}

Write-Step "Configuring Stock service Serve (svc:stock) — Lotto machine Serve 보존, reset 금지"
# 금지: classic `serve --bg http://127.0.0.1:3000` (lottolab machine endpoint를 :3000으로 덮어씀)
$ensure = Join-Path $root "ops\ensure_stock_mobile_access.ps1"
if (-not (Test-Path -LiteralPath $ensure)) {
    throw "missing ensure script: $ensure"
}
& powershell.exe -NoProfile -ExecutionPolicy Bypass -File $ensure -ProjectRoot $root | Out-Host

$serveStatus = (Invoke-Ts -Exe $ts -Args @("serve", "status") | Out-String)
Write-Step "SERVE STATUS:`n$serveStatus"

$funnelAfter = (Invoke-Ts -Exe $ts -Args @("funnel", "status") | Out-String)
Write-Step "FUNNEL STATUS:`n$funnelAfter"

$httpsUrl = "https://stock.tail3bf7b2.ts.net"
if ($serveStatus -match 'https://stock\.[^\s]+') {
    $httpsUrl = $Matches[0].TrimEnd('/', '.')
}

$ip = $null
$dns = $null
try {
    $ip = (Invoke-Ts -Exe $ts -Args @("ip", "-4") | Out-String).Trim()
} catch { }
try {
    $dns = (Invoke-Ts -Exe $ts -Args @("status", "--self", "--json") | Out-String)
} catch { }

Write-Host ""
Write-Host "MOBILE_ACCESS_URL:" -ForegroundColor Green
if ($httpsUrl) {
    Write-Host "$httpsUrl/mobile" -ForegroundColor Green
} else {
    Write-Host "(parse serve status for https://...ts.net)/mobile" -ForegroundColor Yellow
}
Write-Host ""

$evidence = [ordered]@{
    FINAL_VERDICT              = "TAILSCALE_MOBILE_HTTPS_READY"
    INSTALLED                  = $true
    LOGGED_IN                  = $true
    TAILSCALE_IPV4             = $ip
    SERVE_ENABLED              = $true
    SERVE_TARGET               = "svc:stock -> http://127.0.0.1:$FrontendPort"
    HTTPS_URL                  = $httpsUrl
    MOBILE_ACCESS_URL          = if ($httpsUrl) { "$httpsUrl/mobile" } else { $null }
    FUNNEL_ENABLED             = $false
    TAILNET_ONLY               = $true
    BACKEND_DIRECT_EXPOSURE    = $false
    PUBLIC_INTERNET_EXPOSURE   = $false
    PHONE_ACTION_REQUIRED      = $true
    LTE_5G_TEST_REQUIRED       = $true
    NEXT_ACTION                = "PHYSICAL_PHONE_LTE_PWA_VERIFY"
    SERVE_STATUS_RAW           = $serveStatus
    FUNNEL_STATUS_RAW          = $funnelAfter
    TIMESTAMP_UTC              = (Get-Date).ToUniversalTime().ToString("o")
}
($evidence | ConvertTo-Json -Depth 8) | Set-Content -Encoding UTF8 (Join-Path $runDir "k_tailscale_mobile_https_setup.json")
Write-Step "Evidence written: .run/k_tailscale_mobile_https_setup.json"
exit 0
