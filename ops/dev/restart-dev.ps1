#Requires -Version 5.1
<#
.SYNOPSIS
  개발용 Backend/Frontend 재시작
#>
[CmdletBinding()]
param(
    [string]$ProjectRoot = "",
    [int]$BackendPort = 8000,
    [int]$FrontendPort = 3000,
    [int]$PortWaitSec = 30,
    [switch]$NoBrowser
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

function Write-Step([string]$Message) {
    Write-Host "[restart-dev] $Message"
}

function Get-ListenerPid([int]$Port) {
    try {
        $conn = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue |
            Select-Object -First 1
        if ($null -ne $conn -and $conn.OwningProcess -gt 0) {
            return [int]$conn.OwningProcess
        }
    } catch {}
    return $null
}

if ([string]::IsNullOrWhiteSpace($ProjectRoot)) {
    $ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
}

$StopScript = Join-Path $PSScriptRoot "stop-dev.ps1"
$StartScript = Join-Path $PSScriptRoot "start-dev.ps1"

Write-Step "stopping..."
& powershell.exe -NoProfile -ExecutionPolicy Bypass -File $StopScript `
    -ProjectRoot $ProjectRoot `
    -BackendPort $BackendPort `
    -FrontendPort $FrontendPort
$stopCode = $LASTEXITCODE
if ($stopCode -ne 0) {
    Write-Host "[restart-dev] stop-dev exited with code $stopCode (continuing)" -ForegroundColor Yellow
}

Write-Step "waiting for ports $BackendPort / $FrontendPort to free..."
$deadline = (Get-Date).AddSeconds($PortWaitSec)
while ((Get-Date) -lt $deadline) {
    $be = Get-ListenerPid $BackendPort
    $fe = Get-ListenerPid $FrontendPort
    if ($null -eq $be -and $null -eq $fe) {
        Write-Step "ports free"
        break
    }
    Start-Sleep -Milliseconds 500
}
$beLeft = Get-ListenerPid $BackendPort
$feLeft = Get-ListenerPid $FrontendPort
if ($null -ne $beLeft -or $null -ne $feLeft) {
    Write-Host "[FAIL] ports still in use after wait (backend=$beLeft frontend=$feLeft). Not killing foreign processes." -ForegroundColor Red
    exit 2
}

Write-Step "starting..."
if ($NoBrowser) {
    & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $StartScript `
        -ProjectRoot $ProjectRoot -NoBrowser
} else {
    & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $StartScript `
        -ProjectRoot $ProjectRoot
}
exit $LASTEXITCODE
