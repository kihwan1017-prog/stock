# stock-platform API 포트 리스너만 안전하게 종료 (무차별 python kill 금지)
param(
    [Parameter(Mandatory = $true)][int]$Port,
    [string]$ProjectRoot = ""
)

$ErrorActionPreference = "Continue"
Set-StrictMode -Version Latest

function Get-ListenerPid([int]$ListenPort) {
    try {
        $conn = Get-NetTCPConnection -LocalPort $ListenPort -State Listen -ErrorAction SilentlyContinue |
            Select-Object -First 1
        if ($null -ne $conn -and $conn.OwningProcess -gt 0) {
            return [int]$conn.OwningProcess
        }
    } catch {}
    return $null
}

function Get-ProcessCommandLine([int]$ProcessId) {
    try {
        $proc = Get-CimInstance Win32_Process -Filter "ProcessId=$ProcessId" -ErrorAction Stop
        if ($null -eq $proc -or $null -eq $proc.CommandLine) { return "" }
        return [string]$proc.CommandLine
    } catch {
        return ""
    }
}

function Test-StockPlatformApiProcess([int]$ProcessId, [string]$ProjectRootPath) {
    $commandLine = Get-ProcessCommandLine -ProcessId $ProcessId
    if ([string]::IsNullOrWhiteSpace($commandLine)) { return $false }

    $root = $ProjectRootPath.TrimEnd("\", "/")
    $rootAlt = $root -replace "\\", "/"
    if ($commandLine -like "*$root*" -or $commandLine -like "*$rootAlt*") { return $true }
    if ($commandLine -match 'stock_platform\.api\.main:app|uvicorn\.exe') { return $true }
    return $false
}

if ([string]::IsNullOrWhiteSpace($ProjectRoot)) {
    $ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
}
$ProjectRoot = $ProjectRoot.TrimEnd("\", "/")

$listenerPid = Get-ListenerPid -ListenPort $Port
if ($null -eq $listenerPid) {
    Write-Host "[stop] no listener on port $Port"
    exit 0
}

if (-not (Test-StockPlatformApiProcess -ProcessId $listenerPid -ProjectRootPath $ProjectRoot)) {
    Write-Host "[stop] port $Port listener PID=$listenerPid is not stock-platform API — skip (safety)"
    exit 0
}

Write-Host "[stop] killing stock-platform API on port $Port PID=$listenerPid"
& taskkill.exe /PID $listenerPid /T /F 2>$null | Out-Null
Start-Sleep -Milliseconds 400

$remaining = Get-ListenerPid -ListenPort $Port
if ($null -ne $remaining) {
    Write-Host "[stop] WARNING port $Port still listening PID=$remaining"
    exit 1
}

Write-Host "[stop] port $Port free"
exit 0
