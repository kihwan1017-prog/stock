param(
    [string]$TaskName = "StockPlatformScheduler"
)

$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent $PSScriptRoot
$pythonExe = Join-Path $projectRoot ".venv\Scripts\python.exe"
$runner = Join-Path $projectRoot "scripts\run_scheduler.py"

if (-not (Test-Path $pythonExe)) {
    throw "Python executable not found: $pythonExe"
}

if (-not (Test-Path $runner)) {
    throw "Scheduler runner not found: $runner"
}

$action = New-ScheduledTaskAction `
    -Execute $pythonExe `
    -Argument "`"$runner`"" `
    -WorkingDirectory $projectRoot

$trigger = New-ScheduledTaskTrigger `
    -AtStartup

$settings = New-ScheduledTaskSettingsSet `
    -StartWhenAvailable `
    -RestartCount 3 `
    -RestartInterval (New-TimeSpan -Minutes 1) `
    -ExecutionTimeLimit (New-TimeSpan -Days 3650)

Register-ScheduledTask `
    -TaskName $TaskName `
    -Action $action `
    -Trigger $trigger `
    -Settings $settings `
    -Description "Stock Platform APScheduler service" `
    -RunLevel Highest `
    -Force

Write-Host "등록 완료: $TaskName"
Write-Host "수동 시작:"
Write-Host "Start-ScheduledTask -TaskName `"$TaskName`""
