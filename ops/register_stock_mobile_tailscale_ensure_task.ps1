#Requires -Version 5.1
<#
.SYNOPSIS
  Register/update Task Scheduler: StockMobileTailscaleEnsure (durable self-heal).
.DESCRIPTION
  - Does NOT restart backend / trading
  - Independent of StockPlatformScheduler
  - Idempotent: re-run updates the same task
  - Prefer AtStartup(+90s) + AtLogOn
  - Elevation 없으면 기존 task Action만 갱신 + 즉시 1회 실행 시도
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

$arg = "-NoProfile -ExecutionPolicy Bypass -File `"$scriptPath`" -ProjectRoot `"$ProjectRoot`""
$action = New-ScheduledTaskAction -Execute "powershell.exe" -Argument $arg -WorkingDirectory $ProjectRoot

$boot = New-ScheduledTaskTrigger -AtStartup
$boot.Delay = "PT90S"
$logon = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME

$settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -StartWhenAvailable `
    -MultipleInstances IgnoreNew `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 10)

$principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType Interactive -RunLevel Limited

$registered = $false
try {
    Register-ScheduledTask `
        -TaskName $taskName `
        -Action $action `
        -Trigger @($boot, $logon) `
        -Settings $settings `
        -Principal $principal `
        -Force | Out-Null
    $registered = $true
    Write-Host "[register] $taskName FULL (AtStartup+90s, AtLogOn)"
} catch {
    Write-Host "[register] FULL register denied: $($_.Exception.Message)"
    # 권한 부족 시: 기존 task Action만이라도 최신 ensure 경로로 갱신
    try {
        Set-ScheduledTask -TaskName $taskName -Action $action -ErrorAction Stop | Out-Null
        Write-Host "[register] ACTION updated on existing $taskName (triggers unchanged — elevate to add AtStartup)"
    } catch {
        Write-Host "[register] ACTION update also denied: $($_.Exception.Message)"
        Write-Host "[register] HUMAN_ACTION: elevated PowerShell에서 이 스크립트 재실행 필요"
    }
}

if ($RunNow -or $registered) {
    try {
        Start-ScheduledTask -TaskName $taskName -ErrorAction Stop
        Start-Sleep -Seconds 5
        $info = Get-ScheduledTaskInfo -TaskName $taskName
        Write-Host "[register] LastRun=$($info.LastRunTime) LastResult=$($info.LastTaskResult)"
    } catch {
        Write-Host "[register] Start-ScheduledTask: $($_.Exception.Message)"
    }
}

Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue | Format-List TaskName, State
$trig = (Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue).Triggers
if ($null -ne $trig) {
    $trig | ForEach-Object { Write-Host ("[register] trigger=" + $_.CimClass.CimClassName + " delay=" + $_.Delay) }
}
exit 0
