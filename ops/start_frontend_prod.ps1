#Requires -Version 5.1
<#
.SYNOPSIS
  LIVE/운영용 Frontend 기동 — next start (production), next dev 금지.
.DESCRIPTION
  - Idempotent: :3000 HTTP OK면 ALREADY_RUNNING / skip
  - .next build 없으면 FAIL (부팅마다 npm run build 금지)
  - Backend / trading / Tailscale config 미변경
.NOTES
  WRK-20260906-STOCK-FRONTEND-PROD-AUTOSTART-V1
#>
[CmdletBinding()]
param(
    [string]$ProjectRoot = "",
    [int]$FrontendPort = 3000,
    [string]$FrontendHost = "0.0.0.0",
    [int]$ReadyTimeoutSec = 90,
    [switch]$Force
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

function Write-Step([string]$Message) {
    Write-Host "[start-frontend-prod] $Message"
}

if ([string]::IsNullOrWhiteSpace($ProjectRoot)) {
    $ProjectRoot = Split-Path -Parent $PSScriptRoot
    if ((Split-Path -Leaf $PSScriptRoot) -ieq "ops") {
        $ProjectRoot = Split-Path -Parent $PSScriptRoot
    }
}

$FrontendDir = Join-Path $ProjectRoot "frontend"
$PackageJson = Join-Path $FrontendDir "package.json"
$BuildId = Join-Path $FrontendDir ".next\BUILD_ID"
$NpmCmd = (Get-Command npm.cmd -ErrorAction SilentlyContinue)
if ($null -eq $NpmCmd) { $NpmCmd = Get-Command npm -ErrorAction SilentlyContinue }
$NodeCmd = Get-Command node -ErrorAction SilentlyContinue

$RunDir = Join-Path $ProjectRoot ".run"
$LogDir = Join-Path $ProjectRoot "logs\frontend"
New-Item -ItemType Directory -Force -Path $RunDir, $LogDir | Out-Null
$FrontendPidFile = Join-Path $RunDir "frontend.prod.pid"
$ListenPidFile = Join-Path $RunDir "frontend.prod.listen.pid"
$FrontendLog = Join-Path $LogDir ("next_prod_{0:yyyyMMdd_HHmmss}.log" -f (Get-Date))

function Test-PortListening([int]$Port) {
    try {
        $conn = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue |
            Select-Object -First 1
        if ($null -ne $conn -and $conn.OwningProcess -gt 0) {
            return [int]$conn.OwningProcess
        }
    } catch { }
    $lines = netstat -ano | Select-String -Pattern ":$Port\s+.*LISTENING"
    foreach ($line in $lines) {
        $parts = ($line.ToString() -split "\s+") | Where-Object { $_ -ne "" }
        if ($parts.Count -ge 5) { return [int]$parts[-1] }
    }
    return $null
}

function Test-HttpOk([string]$Url) {
    try {
        $resp = Invoke-WebRequest -Uri $Url -UseBasicParsing -TimeoutSec 5
        return ($resp.StatusCode -ge 200 -and $resp.StatusCode -lt 500)
    } catch { return $false }
}

function Test-IsNextListenPid([int]$ProcessId) {
    try {
        $p = Get-CimInstance Win32_Process -Filter "ProcessId=$ProcessId" -ErrorAction SilentlyContinue
        if ($null -eq $p) { return $false }
        $cmd = [string]$p.CommandLine
        if ($cmd -match 'next(\\|/| )start|next-server|node_modules\\next') { return $true }
        # 포트만 점유 중이면 보수적으로 true (중복 기동 방지)
        return $true
    } catch {
        return $true
    }
}

if (-not (Test-Path -LiteralPath $FrontendDir)) {
    throw "FRONTEND_DIR missing: $FrontendDir"
}
if (-not (Test-Path -LiteralPath $PackageJson)) {
    throw "package.json missing: $PackageJson"
}
if ($null -eq $NodeCmd) { throw "node not found in PATH" }
if ($null -eq $NpmCmd) { throw "npm not found in PATH" }

$probeUrl = "http://127.0.0.1:$FrontendPort/"
$existing = Test-PortListening $FrontendPort
if ($null -ne $existing -and -not $Force) {
    if (Test-HttpOk $probeUrl) {
        Write-Step "ALREADY_RUNNING PID=$existing — skip (use -Force to replace)"
        Set-Content -LiteralPath $ListenPidFile -Value $existing -Encoding ascii
        exit 0
    }
    Write-Step "port $FrontendPort listen PID=$existing but HTTP not ready — wait briefly"
}

if ($Force -and $null -ne $existing) {
    Write-Step "Force requested but refusing to kill non-stock processes blindly"
    Write-Step "Stop existing Next manually if needed, then re-run without orphan risk"
    throw "Force stop of :$FrontendPort not automated (safety)"
}

if (-not (Test-Path -LiteralPath $BuildId)) {
    Write-Step "NEXT_BUILD_MISSING: $BuildId"
    throw "production .next build missing — run 'npm run build' in frontend before startup task"
}

# 이미 HTTP OK면 위에서 exit. 여기까지 오면 기동 필요.
Write-Step "NO next dev · npm run start · port=$FrontendPort · host=$FrontendHost"
Write-Step "FRONTEND_DIR=$FrontendDir build=$BuildId"

$npmPath = $NpmCmd.Source
$frontendCmd = @"
`$ErrorActionPreference='Continue'
Set-Location -LiteralPath '$FrontendDir'
`$env:NODE_ENV='production'
`$env:PORT='$FrontendPort'
# Google/API env는 Next build/runtime 파일·rewrite 사용 — 여기서 LIVE env override 금지
& '$npmPath' run start -- --hostname $FrontendHost --port $FrontendPort *>> '$FrontendLog'
"@

$frontendProc = Start-Process -FilePath "powershell.exe" `
    -ArgumentList @("-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", $frontendCmd) `
    -WorkingDirectory $FrontendDir `
    -WindowStyle Minimized `
    -PassThru
Set-Content -LiteralPath $FrontendPidFile -Value $frontendProc.Id -Encoding ascii
Write-Step "launcher PID=$($frontendProc.Id) log=$FrontendLog"

$deadline = (Get-Date).AddSeconds($ReadyTimeoutSec)
while ((Get-Date) -lt $deadline) {
    if (Test-HttpOk $probeUrl) {
        $listen = Test-PortListening $FrontendPort
        if ($null -ne $listen) {
            Set-Content -LiteralPath $ListenPidFile -Value $listen -Encoding ascii
        }
        Write-Step "READY HTTP=$probeUrl listenPID=$listen"
        exit 0
    }
    Start-Sleep -Milliseconds 800
}
throw "frontend health timeout: $probeUrl (log=$FrontendLog)"
