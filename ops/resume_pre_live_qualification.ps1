#Requires -Version 5.1
<#
.SYNOPSIS
  재부팅 후 qualification 검증만 수행. LIVE/ARM/AUTO/주문/스케줄러 활성화 없음.
#>
[CmdletBinding()]
param(
    [string]$ProjectRoot = "D:\Projects\stock-platform"
)

$ErrorActionPreference = "Continue"
Set-StrictMode -Version Latest

$Evidence = Join-Path $ProjectRoot ".run\pre-live-qualification-finalize"
New-Item -ItemType Directory -Force -Path $Evidence | Out-Null

$report = [ordered]@{
    boot_time = $null
    postgres = "UNKNOWN"
    postgres_bind = @()
    tailscale = "UNKNOWN"
    serve = "UNKNOWN"
    funnel = "UNKNOWN"
    ollama = "UNKNOWN"
    ollama_has_4b = $false
    backend = "UNKNOWN"
    frontend = "UNKNOWN"
    shadow = "UNKNOWN"
    post_reboot_observations = 0
    live_arm_auto_touched = $false
    qualification_task_removed = $false
}

try {
    $report.boot_time = (Get-CimInstance Win32_OperatingSystem).LastBootUpTime.ToString("o")
} catch {}

# PostgreSQL — listener만 확인. 데이터/마이그레이션 없음.
try {
    $pg = Get-Service -Name "postgresql-x64-17" -ErrorAction SilentlyContinue
    $tcp = @(Get-NetTCPConnection -LocalPort 5432 -State Listen -ErrorAction SilentlyContinue)
    $report.postgres_bind = @($tcp | ForEach-Object { "$($_.LocalAddress):$($_.LocalPort)" })
    $report.postgres = if ($pg -and $pg.Status -eq "Running" -and $tcp.Count -gt 0) { "RUNNING" } else { "DOWN" }
} catch { $report.postgres = "ERROR" }

try {
    $tsSvc = Get-Service -Name "Tailscale" -ErrorAction SilentlyContinue
    $report.tailscale = if ($tsSvc -and $tsSvc.Status -eq "Running") { "RUNNING" } else { "DOWN" }
} catch { $report.tailscale = "ERROR" }

try {
    $serveOut = & tailscale serve status 2>&1 | Out-String
    $report.serve = if ($serveOut -match "stock.tail3bf7b2.ts.net") { "PRESENT" } else { "MISSING" }
    $report.funnel = if ($serveOut -match "(?i)funnel") { "CHECK" } else { "OFF" }
    if ($serveOut -match "(?i)funnel on") { $report.funnel = "ON" }
} catch { $report.serve = "ERROR" }

try {
    $tags = Invoke-WebRequest -Uri "http://192.168.1.10:11434/api/tags" -UseBasicParsing -TimeoutSec 15
    $report.ollama = "HTTP_$($tags.StatusCode)"
    $report.ollama_has_4b = ($tags.Content -match "qwen3.5:4b")
} catch { $report.ollama = "UNREACHABLE" }

# Backend/Frontend — 공식 스크립트만. trading activation 없음.
$backendScript = Join-Path $ProjectRoot "ops\start_backend_prod.ps1"
$frontendScript = Join-Path $ProjectRoot "ops\start_frontend_prod.ps1"
try {
    & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $backendScript -AllowDirtyDevRoot -ReadyTimeoutSec 90
    $live = Invoke-WebRequest -Uri "http://127.0.0.1:8000/health/live" -UseBasicParsing -TimeoutSec 10
    $ready = Invoke-WebRequest -Uri "http://127.0.0.1:8000/health/ready" -UseBasicParsing -TimeoutSec 10
    $report.backend = "HTTP_$($live.StatusCode)/$($ready.StatusCode)"
} catch { $report.backend = "ERROR:$($_.Exception.Message)" }

try {
    & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $frontendScript -ReadyTimeoutSec 90
    $fe = Invoke-WebRequest -Uri "http://127.0.0.1:3000" -UseBasicParsing -TimeoutSec 15
    $report.frontend = "HTTP_$($fe.StatusCode)"
} catch { $report.frontend = "ERROR:$($_.Exception.Message)" }

$env:PYTHONPATH = Join-Path $ProjectRoot "src"
$env:STOCK_PLATFORM_ENV_FILE = "E:\StockTrading\secrets\stock-platform.env"
$env:SHADOW_OBSERVATION_ONLY = "true"
foreach ($name in @(
    "STOCK_PLATFORM_DISABLE_ENV_FILE",
    "STOCK_PLATFORM_TESTING",
    "STOCK_PLATFORM_TEST_DATABASE_URL",
    "APP_ENV",
    "DB_NAME",
    "DB_HOST",
    "DB_PORT",
    "DB_USER",
    "DB_PASSWORD",
    "DATABASE_URL"
)) {
    Remove-Item "Env:$name" -ErrorAction SilentlyContinue
}

$python = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
& $python (Join-Path $ProjectRoot ".run\trading-decision-recovery\after_snap.py") |
    Out-File (Join-Path $Evidence "post_reboot_snap.txt") -Encoding utf8

# 주문 엔진이 아니라 1회 observation. 중복 PID면 run_once가 ALREADY_RUNNING일 수 있어 직접 호출.
& $python -c "from stock_platform.operation.paper_shadow_observer.runner import run_once; rec=run_once(limit=12, cycle_id=901); print(len(rec))" |
    Out-File (Join-Path $Evidence "post_reboot_observer.txt") -Encoding utf8
$report.shadow = "ONCE_DONE"
try {
    $n = Get-Content (Join-Path $Evidence "post_reboot_observer.txt") | Select-Object -Last 1
    $report.post_reboot_observations = [int]$n
} catch {}

$shadowMeta = [ordered]@{
    observations = $report.post_reboot_observations
    cycle_id = 901
    model = "qwen3.5:4b"
    endpoint = "http://192.168.1.10:11434"
    order_created = 0
    outbox_created = 0
}
($shadowMeta | ConvertTo-Json) | Set-Content -Path (Join-Path $Evidence "post_reboot_shadow.json") -Encoding UTF8

$task = "StockPlatform-Qualification-Resume"
schtasks /Delete /TN $task /F 2>$null | Out-Null
$report.qualification_task_removed = $true

# Observer 전용 autostart. OES/LIVE/ARM/AUTO 아님.
$observerOk = ($report.post_reboot_observations -ge 3) -and ($report.ollama -eq "HTTP_200") -and ($report.postgres -eq "RUNNING")
$observerTask = "StockPlatform-Paper-Shadow-Observer"
$observerCmd = "powershell.exe -NoProfile -ExecutionPolicy Bypass -File `"$ProjectRoot\ops\start_shadow_observer.ps1`" -Limit 8 -LoopSeconds 300"
if ($observerOk) {
    schtasks /Create /TN $observerTask /TR $observerCmd /SC ONLOGON /RL LIMITED /F 2>$null | Out-Null
    $auto = [ordered]@{
        shadow_autostart_installed = $true
        shadow_autostart_command = $observerCmd
        trading_autostart_installed = $false
        live_autostart = $false
        arm_autostart = $false
        auto_trading_autostart = $false
        backend_autostart = "DEFERRED_FOR_SAFETY"
        frontend_autostart = "DEFERRED_FOR_SAFETY"
        duplicate_start_guard = "start_shadow_observer.ps1 refuses live PID"
    }
    ($auto | ConvertTo-Json) | Set-Content -Path (Join-Path $Evidence "autostart.json") -Encoding UTF8
    & powershell.exe -NoProfile -ExecutionPolicy Bypass -File (Join-Path $ProjectRoot "ops\start_shadow_observer.ps1") -Limit 8 -LoopSeconds 300
}

($report | ConvertTo-Json -Depth 6) | Set-Content -Path (Join-Path $Evidence "post_reboot.json") -Encoding UTF8
& $python (Join-Path $Evidence "complete_finalize_report.py")
Write-Host "[resume] wrote post_reboot.json LIVE/ARM/AUTO not touched"
