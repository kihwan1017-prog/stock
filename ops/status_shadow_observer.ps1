#Requires -Version 5.1
<#
.SYNOPSIS
  PAPER SHADOW observer 상태. 주문 제어 없음.
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
$StatusFile = Join-Path $ProjectRoot ".run\paper-shadow-observation\status.json"
$running = $false
if (Test-Path -LiteralPath $PidFile) {
    $raw = (Get-Content -LiteralPath $PidFile -Raw).Trim()
    if ($raw -match "^\d+$") {
        $running = $null -ne (Get-Process -Id ([int]$raw) -ErrorAction SilentlyContinue)
    }
}
Write-Host "[shadow-observer] RUNNING=$running"
if (Test-Path -LiteralPath $StatusFile) {
    Get-Content -LiteralPath $StatusFile -Raw
} else {
    Write-Host '{"state":"STOPPED","reason":"NO_STATUS_FILE"}'
}
