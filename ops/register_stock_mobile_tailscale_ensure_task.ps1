#Requires -Version 5.1
<#
.SYNOPSIS
  Register/update Task Scheduler: StockMobileTailscaleEnsure (boot self-heal).
.DESCRIPTION
  - Does NOT restart backend / trading
  - Independent of StockPlatformScheduler
  - Idempotent: re-run updates the same task
#>
[CmdletBinding()]
param(
    [string]$ProjectRoot = "",
    [switch]$Unregister
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

$arg = "-NoProfile -ExecutionPolicy Bypass -File `"$scriptPath`""
$action = New-ScheduledTaskAction -Execute "powershell.exe" -Argument $arg -WorkingDirectory $ProjectRoot
# AtLogOn (no admin). Prefer this over AtStartup+Highest when UAC blocks registration.
$trigger = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable -MultipleInstances IgnoreNew

Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger -Settings $settings -Force | Out-Null
Write-Host "[register] $taskName -> $scriptPath (AtLogOn)"
Get-ScheduledTask -TaskName $taskName | Format-List TaskName, State
exit 0
