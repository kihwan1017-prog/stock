#Requires -Version 5.1
<#
.SYNOPSIS
  Register/update Task Scheduler: StockMobileTailscaleEnsure (startup ordering).
.DESCRIPTION
  Canonical chain:
    StockBackendProdEnsure     AtStartup + PT2M
    StockFrontendProdEnsure    AtStartup + PT2M30S
    StockMobileTailscaleEnsure AtStartup + PT5M

  - Action: ensure_stock_mobile_access.ps1 only (History139 logic unchanged)
  - AtLogOn 제거 — Frontend보다 먼저 돌던 재부팅 실패 방지
  - Backend/Frontend/trading 미변경 · serve reset 금지
.NOTES
  WRK-20260906-STOCK-TAILSCALE-STARTUP-ORDERING-V1
#>
[CmdletBinding()]
param(
    [string]$ProjectRoot = "",
    [switch]$Unregister,
    [switch]$RunNow
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

if ([string]::IsNullOrWhiteSpace($ProjectRoot)) {
    $ProjectRoot = Split-Path -Parent $PSScriptRoot
}

$taskName = "StockMobileTailscaleEnsure"
$scriptPath = Join-Path $ProjectRoot "ops\ensure_stock_mobile_access.ps1"
if (-not (Test-Path -LiteralPath $scriptPath)) {
    throw "missing $scriptPath"
}

if ($Unregister) {
    Unregister-ScheduledTask -TaskName $taskName -Confirm:$false -ErrorAction SilentlyContinue
    Write-Host "[register] removed $taskName"
    exit 0
}

# Frontend(+150s) 이후: Tailscale Ensure(+300s / PT5M)
$arg = "-NoProfile -ExecutionPolicy Bypass -File `"$scriptPath`" -ProjectRoot `"$ProjectRoot`""
$action = New-ScheduledTaskAction -Execute "powershell.exe" -Argument $arg -WorkingDirectory $ProjectRoot

$boot = New-ScheduledTaskTrigger -AtStartup
$boot.Delay = "PT5M"

$settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -StartWhenAvailable `
    -MultipleInstances IgnoreNew `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 15)

# Backend/Frontend 등록 패턴과 동일 (Highest + Interactive)
$principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType Interactive -RunLevel Highest

$registered = $false
$adminRequired = $false
try {
    Register-ScheduledTask `
        -TaskName $taskName `
        -Action $action `
        -Trigger $boot `
        -Settings $settings `
        -Principal $principal `
        -Force | Out-Null
    $registered = $true
    Write-Host "[register] $taskName FULL (AtStartup+PT5M) -> $scriptPath"
} catch {
    $adminRequired = $true
    Write-Host "[register] FULL register denied: $($_.Exception.Message)"
    # 권한 부족: Action만 갱신 시도 (Trigger/Principal은 elevate 필요)
    try {
        Set-ScheduledTask -TaskName $taskName -Action $action -ErrorAction Stop | Out-Null
        Write-Host "[register] ACTION updated on existing $taskName (triggers/delay unchanged until elevate)"
    } catch {
        Write-Host "[register] ACTION update also denied: $($_.Exception.Message)"
    }
    Write-Host "[register] ADMIN_UPDATE_REQUIRED=true"
    Write-Host ("[register] ADMIN_COMMAND: powershell -NoProfile -ExecutionPolicy Bypass -File `"$PSCommandPath`" -ProjectRoot `"$ProjectRoot`"")
}

if ($RunNow) {
    try {
        # 현재 FE healthy면 ensure 직접 실행이 Task Start보다 확실
        & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $scriptPath -ProjectRoot $ProjectRoot
        Write-Host "[register] RunNow ensure exit=$LASTEXITCODE"
    } catch {
        Write-Host "[register] RunNow failed: $($_.Exception.Message)"
    }
}

$existing = Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
if ($null -eq $existing) {
    Write-Host "[register] TASK_ABSENT — elevate ADMIN_COMMAND 필요"
    exit 1
}

Write-Host ("[register] STATE=" + $existing.State + " RUNLEVEL=" + $existing.Principal.RunLevel)
$trig = $existing.Triggers
if ($null -ne $trig) {
    @($trig) | ForEach-Object {
        Write-Host ("[register] trigger=" + $_.CimClass.CimClassName + " delay=" + $_.Delay)
    }
} else {
    Write-Host "[register] triggers=null"
}

$act = @($existing.Actions)[0]
Write-Host ("[register] action=" + $act.Execute + " " + $act.Arguments)

# elevatesuccess면 delay가 PT5M인지 표시
$delayOk = $false
foreach ($t in @($trig)) {
    if ($t.CimClass.CimClassName -eq "MSFT_TaskBootTrigger" -and [string]$t.Delay -eq "PT5M") {
        $delayOk = $true
    }
}
Write-Host ("[register] CANONICAL_PT5M=" + $delayOk)
Write-Host ("[register] ADMIN_UPDATE_REQUIRED=" + ($(if ($adminRequired -or -not $delayOk) { "true" } else { "false" })))

if (-not $delayOk) { exit 2 }
exit 0
