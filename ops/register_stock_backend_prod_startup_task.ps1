#Requires -Version 5.1
<#
.SYNOPSIS
  Register AtStartup task: StockBackendProdEnsure (production uvicorn, no reload).
.DESCRIPTION
  PC reboot 후 DEV/hot-reload로 REAL restore가 막히는 재발을 방지.
  - start_backend_prod.ps1 만 호출 (LIVE/ARM 직접 ON 안 함)
  - unattended restore는 backend lifecycle startup이 수행
  - trading policy / 주문 mutation 없음
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

$taskName = "StockBackendProdEnsure"
$scriptPath = Join-Path $ProjectRoot "ops\start_backend_prod.ps1"
if (-not (Test-Path -LiteralPath $scriptPath)) {
    throw "missing $scriptPath"
}

if ($Unregister) {
    Unregister-ScheduledTask -TaskName $taskName -Confirm:$false -ErrorAction SilentlyContinue
    Write-Host "[register] removed $taskName"
    exit 0
}

# AtStartup + delay: Tailscale/DB 기동 여유
$arg = "-NoProfile -ExecutionPolicy Bypass -File `"$scriptPath`" -ProjectRoot `"$ProjectRoot`""
$action = New-ScheduledTaskAction -Execute "powershell.exe" -Argument $arg -WorkingDirectory $ProjectRoot
$boot = New-ScheduledTaskTrigger -AtStartup
$boot.Delay = "PT120S"
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
    Write-Host "[register] $taskName AtStartup+120s -> $scriptPath"
} catch {
    Write-Host "[register] FULL register denied: $($_.Exception.Message)"
    try {
        Set-ScheduledTask -TaskName $taskName -Action $action -ErrorAction Stop | Out-Null
        Write-Host "[register] ACTION updated (elevate to add AtStartup if missing)"
    } catch {
        Write-Host "[register] HUMAN_ACTION: elevated PowerShell에서 재실행 필요: $($_.Exception.Message)"
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
exit 0
