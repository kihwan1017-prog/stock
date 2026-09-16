#Requires -Version 5.1
<#
.SYNOPSIS
  PAPER SHADOW observer 종료. Trading/LIVE 프로세스는 건드리지 않음.
#>
[CmdletBinding()]
param(
    [string]$ProjectRoot = ""
)

$ErrorActionPreference = "Continue"
Set-StrictMode -Version Latest

if ([string]::IsNullOrWhiteSpace($ProjectRoot)) {
    $ProjectRoot = Split-Path -Parent $PSScriptRoot
}

$PidFile = Join-Path $ProjectRoot ".run\shadow-observer.pid"
if (-not (Test-Path -LiteralPath $PidFile)) {
    Write-Host "[shadow-observer] already stopped"
    exit 0
}

$raw = (Get-Content -LiteralPath $PidFile -Raw -ErrorAction SilentlyContinue).Trim()
if ($raw -match "^\d+$") {
    $proc = Get-Process -Id ([int]$raw) -ErrorAction SilentlyContinue
    if ($null -ne $proc) {
        Stop-Process -Id ([int]$raw) -Force -ErrorAction SilentlyContinue
        Write-Host "[shadow-observer] stopped pid=$raw"
    }
}
Remove-Item -LiteralPath $PidFile -Force -ErrorAction SilentlyContinue
Write-Host "[shadow-observer] STOPPED"
