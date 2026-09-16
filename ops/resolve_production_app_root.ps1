#Requires -Version 5.1
<#
.SYNOPSIS
  Resolve canonical CLEAN production app root (committed source only).
.DESCRIPTION
  Development worktree(D:\Projects\stock-platform)가 dirty여도
  production은 STOCK_PLATFORM_PRODUCTION_ROOT 또는
  D:\Projects\stock-platform-runtime 의 committed checkout만 로드한다.

  Secret/DB는 E:\StockTrading\secrets 등 공유 경로를 그대로 쓴다.
  이 스크립트는 파일을 수정하지 않는다.
#>
[CmdletBinding()]
param(
    [string]$PreferredRoot = "",
    [switch]$RequireCleanGit
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

function Test-LooksLikeAppRoot([string]$Root) {
    if ([string]::IsNullOrWhiteSpace($Root)) { return $false }
    if (-not (Test-Path -LiteralPath $Root)) { return $false }
    $main = Join-Path $Root "src\stock_platform\api\main.py"
    $ops = Join-Path $Root "ops\start_backend_prod.ps1"
    return ((Test-Path -LiteralPath $main) -and (Test-Path -LiteralPath $ops))
}

function Test-GitClean([string]$Root) {
    $git = Get-Command git -ErrorAction SilentlyContinue
    if ($null -eq $git) { return $false }
    Push-Location -LiteralPath $Root
    try {
        $porcelain = & git status --porcelain 2>$null
        return [string]::IsNullOrWhiteSpace(($porcelain | Out-String).Trim())
    } finally {
        Pop-Location
    }
}

$candidates = @()
if (-not [string]::IsNullOrWhiteSpace($PreferredRoot)) {
    $candidates += $PreferredRoot.TrimEnd("\", "/")
}
if (-not [string]::IsNullOrWhiteSpace($env:STOCK_PLATFORM_PRODUCTION_ROOT)) {
    $candidates += $env:STOCK_PLATFORM_PRODUCTION_ROOT.TrimEnd("\", "/")
}
$candidates += "D:\Projects\stock-platform-runtime"

$chosen = $null
foreach ($c in $candidates) {
    if (Test-LooksLikeAppRoot $c) {
        if ($RequireCleanGit -and -not (Test-GitClean $c)) {
            continue
        }
        $chosen = $c
        break
    }
}

if ($null -eq $chosen) {
    # legacy fallback: caller script's repo root (may be dirty — caller must gate)
    if (-not [string]::IsNullOrWhiteSpace($PSScriptRoot)) {
        $legacy = Split-Path -Parent $PSScriptRoot
        if (Test-LooksLikeAppRoot $legacy) {
            $chosen = $legacy
        }
    }
}

if ($null -eq $chosen) {
    throw "PRODUCTION_APP_ROOT_UNRESOLVED"
}

# stdout: path only (ops scripts capture)
Write-Output $chosen
