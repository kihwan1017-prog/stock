#Requires -Version 5.1
<#
.SYNOPSIS
  Backend 종료 (포트 리스너 + launcher PID). Frontend는 건드리지 않음.
#>
[CmdletBinding()]
param(
    [string]$ProjectRoot = "",
    [int]$BackendPort = 8000
)

$ErrorActionPreference = "Continue"
Set-StrictMode -Version Latest

if ([string]::IsNullOrWhiteSpace($ProjectRoot)) {
    $ProjectRoot = Split-Path -Parent $PSScriptRoot
    if ((Split-Path -Leaf $PSScriptRoot) -ieq "ops") {
        $ProjectRoot = Split-Path -Parent $PSScriptRoot
    }
}

$RunDir = Join-Path $ProjectRoot ".run"
Write-Host "[stop-backend] port=$BackendPort"

# Prefer existing helper
$stopPort = Join-Path $PSScriptRoot "_stop_port_listener.ps1"
if (Test-Path -LiteralPath $stopPort) {
    & $stopPort -Port $BackendPort
}

foreach ($name in @("backend.pid", "backend.listen.pid")) {
    $pf = Join-Path $RunDir $name
    if (Test-Path -LiteralPath $pf) {
        $raw = (Get-Content -LiteralPath $pf -Raw -ErrorAction SilentlyContinue).Trim()
        if ($raw -match "^\d+$") {
            $pidVal = [int]$raw
            try {
                $p = Get-Process -Id $pidVal -ErrorAction SilentlyContinue
                if ($null -ne $p) {
                    Write-Host "[stop-backend] taskkill /T PID=$pidVal ($name)"
                    cmd.exe /c "taskkill /PID $pidVal /T /F" | Out-Null
                }
            } catch { }
        }
        Remove-Item -LiteralPath $pf -Force -ErrorAction SilentlyContinue
    }
}

# Catch leftover uvicorn --reload watchers on same port
Get-CimInstance Win32_Process -ErrorAction SilentlyContinue |
    Where-Object {
        $_.CommandLine -and
        ($_.CommandLine -match 'uvicorn') -and
        ($_.CommandLine -match "port $BackendPort" -or $_.CommandLine -match "--port $BackendPort")
    } |
    ForEach-Object {
        Write-Host "[stop-backend] leftover uvicorn PID=$($_.ProcessId)"
        cmd.exe /c "taskkill /PID $($_.ProcessId) /T /F" | Out-Null
    }

Start-Sleep -Seconds 1
Write-Host "[stop-backend] done"
