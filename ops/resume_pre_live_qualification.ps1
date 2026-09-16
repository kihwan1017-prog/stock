#Requires -Version 5.1
<#
.SYNOPSIS
  재부팅 후 qualification resume. LIVE/ARM/AUTO/주문 없음.
#>
[CmdletBinding()]
param(
    [string]$ProjectRoot = "D:\Projects\stock-platform"
)

$ErrorActionPreference = "Continue"
Set-StrictMode -Version Latest
$Evidence = Join-Path $ProjectRoot ".run\pre-live-autonomous-qualification"
New-Item -ItemType Directory -Force -Path $Evidence | Out-Null
$report = [ordered]@{
    boot_time = (Get-CimInstance Win32_OperatingSystem).LastBootUpTime.ToString("o")
    postgres = "UNKNOWN"
    tailscale = "UNKNOWN"
    ollama = "UNKNOWN"
    backend = "UNKNOWN"
    frontend = "UNKNOWN"
    shadow = "UNKNOWN"
    post_reboot_observations = 0
}

try {
    $tcp = Get-NetTCPConnection -LocalPort 5432 -State Listen -ErrorAction SilentlyContinue
    $report.postgres = if ($tcp) { "RUNNING" } else { "DOWN" }
} catch { $report.postgres = "ERROR" }

try {
    $ts = & tailscale status --json 2>$null | ConvertFrom-Json
    $report.tailscale = [string]$ts.BackendState
} catch { $report.tailscale = "ERROR" }

try {
    $tags = Invoke-WebRequest -Uri "http://192.168.1.10:11434/api/tags" -UseBasicParsing -TimeoutSec 10
    $report.ollama = "HTTP_$($tags.StatusCode)"
} catch { $report.ollama = "UNREACHABLE" }

$env:PYTHONPATH = Join-Path $ProjectRoot "src"
$env:STOCK_PLATFORM_ENV_FILE = "E:\StockTrading\secrets\stock-platform.env"
$env:SHADOW_OBSERVATION_ONLY = "true"
Remove-Item Env:STOCK_PLATFORM_DISABLE_ENV_FILE -ErrorAction SilentlyContinue
$python = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
& $python (Join-Path $ProjectRoot ".run\trading-decision-recovery\after_snap.py") | Out-File (Join-Path $Evidence "reboot_post_snap.json") -Encoding utf8

& $python -c "from stock_platform.operation.paper_shadow_observer.runner import run_once; rec=run_once(limit=5, cycle_id=900); print(len(rec))" | Out-File (Join-Path $Evidence "reboot_observer.txt") -Encoding utf8
$report.shadow = "ONCE_DONE"
try {
    $n = Get-Content (Join-Path $Evidence "reboot_observer.txt") | Select-Object -Last 1
    $report.post_reboot_observations = [int]$n
} catch {}

$task = "StockPlatform-Qualification-Resume"
schtasks /Delete /TN $task /F 2>$null | Out-Null
$report.qualification_task_removed = $true

($report | ConvertTo-Json) | Set-Content -Path (Join-Path $Evidence "reboot_post.json") -Encoding UTF8
Write-Host "[resume] wrote reboot_post.json LIVE/ARM/AUTO not touched"
