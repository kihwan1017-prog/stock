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
    $resolveScript = Join-Path $PSScriptRoot "resolve_production_app_root.ps1"
    if (Test-Path -LiteralPath $resolveScript) {
        $ProjectRoot = (& powershell.exe -NoProfile -ExecutionPolicy Bypass -File $resolveScript).Trim()
    } else {
        $ProjectRoot = Split-Path -Parent $PSScriptRoot
    }
}
$ProjectRoot = $ProjectRoot.TrimEnd("\", "/")

# dirty development root로 boot/health ensure가 붙지 않도록 방어
$devRoot = "D:\Projects\stock-platform"
if ($ProjectRoot.ToLowerInvariant() -eq $devRoot.ToLowerInvariant()) {
    $resolveScript = Join-Path $PSScriptRoot "resolve_production_app_root.ps1"
    if (Test-Path -LiteralPath $resolveScript) {
        $alt = (& powershell.exe -NoProfile -ExecutionPolicy Bypass -File $resolveScript `
            -PreferredRoot "D:\Projects\stock-platform-runtime").Trim()
        if ($alt.ToLowerInvariant() -ne $devRoot.ToLowerInvariant()) {
            Write-Host "[register] redirect ProjectRoot dirty-dev -> $alt"
            $ProjectRoot = $alt
        }
    }
}

$taskName = "StockBackendProdEnsure"
$scriptPath = Join-Path $ProjectRoot "ops\start_backend_prod.ps1"
if (-not (Test-Path -LiteralPath $scriptPath)) {
    throw "missing $scriptPath"
}
Write-Host "[register] production_root=$ProjectRoot"

if ($Unregister) {
    Unregister-ScheduledTask -TaskName $taskName -Confirm:$false -ErrorAction SilentlyContinue
    Unregister-ScheduledTask -TaskName "StockBackendProdHealthEnsure" -Confirm:$false -ErrorAction SilentlyContinue
    Write-Host "[register] removed $taskName + StockBackendProdHealthEnsure"
    exit 0
}

# AtStartup + delay: Tailscale/DB 기동 여유
# Periodic health ensure는 별도 태스크(StockBackendProdHealthEnsure)로 등록
#   — Highest RunLevel 부트 태스크 변경이 UAC로 막혀도 Limited로 5분 ensure 가능
#   start_backend_prod.ps1 은 healthy listen 이면 skip (무한 restart loop 아님)
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

# 24x7 mid-session death recovery (reboot 없이)
$healthTaskName = "StockBackendProdHealthEnsure"
$healthSettings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -StartWhenAvailable `
    -WakeToRun `
    -MultipleInstances IgnoreNew `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 15)
$healthPrincipal = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType Interactive -RunLevel Limited
$periodic = New-ScheduledTaskTrigger -Once -At ((Get-Date).Date) `
    -RepetitionInterval (New-TimeSpan -Minutes 5) `
    -RepetitionDuration (New-TimeSpan -Days 3650)
try {
    Register-ScheduledTask `
        -TaskName $healthTaskName `
        -Action $action `
        -Trigger $periodic `
        -Settings $healthSettings `
        -Principal $healthPrincipal `
        -Force | Out-Null
    Write-Host "[register] $healthTaskName PT5M ensure + WakeToRun -> $scriptPath"
} catch {
    Write-Host "[register] HEALTH ensure failed: $($_.Exception.Message)"
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
