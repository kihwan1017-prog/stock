#Requires -Version 5.1
<#
.SYNOPSIS
  Register AtStartup task: StockFrontendProdEnsure (Next production :3000).
.DESCRIPTION
  Backend AtStartup(+120s) 이후 실행되도록 Delay PT150S.
  - start_frontend_prod.ps1 만 호출
  - Backend / LIVE / ARM / Tailscale serve reset 금지
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

$taskName = "StockFrontendProdEnsure"
$scriptPath = Join-Path $ProjectRoot "ops\start_frontend_prod.ps1"
if (-not (Test-Path -LiteralPath $scriptPath)) {
    throw "missing $scriptPath"
}

if ($Unregister) {
    Unregister-ScheduledTask -TaskName $taskName -Confirm:$false -ErrorAction SilentlyContinue
    Write-Host "[register] removed $taskName"
    exit 0
}

# Backend(+120s) 이후 frontend(+150s)
$arg = "-NoProfile -ExecutionPolicy Bypass -File `"$scriptPath`" -ProjectRoot `"$ProjectRoot`""
$action = New-ScheduledTaskAction -Execute "powershell.exe" -Argument $arg -WorkingDirectory $ProjectRoot
$boot = New-ScheduledTaskTrigger -AtStartup
$boot.Delay = "PT150S"
$settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -StartWhenAvailable `
    -MultipleInstances IgnoreNew `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 15)
$principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType Interactive -RunLevel Highest

try {
    Register-ScheduledTask `
        -TaskName $taskName `
        -Action $action `
        -Trigger $boot `
        -Settings $settings `
        -Principal $principal `
        -Force | Out-Null
    Write-Host "[register] $taskName AtStartup+150s -> $scriptPath"
} catch {
    Write-Host "[register] FULL register denied: $($_.Exception.Message)"
    try {
        Set-ScheduledTask -TaskName $taskName -Action $action -ErrorAction Stop | Out-Null
        Write-Host "[register] ACTION updated (elevate to add AtStartup if missing)"
    } catch {
        Write-Host "[register] HUMAN_ACTION: elevated PowerShell에서 재실행 필요"
        Write-Host "[register] ADMIN_COMMAND: powershell -NoProfile -ExecutionPolicy Bypass -File `"$PSCommandPath`" -ProjectRoot `"$ProjectRoot`""
    }
}

if ($RunNow) {
    try {
        Start-ScheduledTask -TaskName $taskName -ErrorAction Stop
        Write-Host "[register] started $taskName"
    } catch {
        Write-Host "[register] RunNow via direct script"
        & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $scriptPath -ProjectRoot $ProjectRoot
    }
}

Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue | Format-List TaskName, State
$existingTask = Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
if ($null -ne $existingTask) {
    $trig = $existingTask.Triggers
    if ($null -ne $trig) {
        @($trig) | ForEach-Object { Write-Host ("[register] trigger=" + $_.CimClass.CimClassName + " delay=" + $_.Delay) }
    }
} else {
    Write-Host "[register] TASK_ABSENT — elevate ADMIN_COMMAND 필요"
}
exit 0
