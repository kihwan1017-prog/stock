# NSSM 서비스 제거
param(
    [string]$ServiceName = "StockPlatformAPI"
)

$ErrorActionPreference = "Stop"
$id = [Security.Principal.WindowsIdentity]::GetCurrent()
$p = New-Object Security.Principal.WindowsPrincipal($id)
if (-not $p.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    throw "관리자 권한 PowerShell 에서 실행하세요."
}

if (-not (Get-Command nssm -ErrorAction SilentlyContinue)) {
    throw "nssm 없음"
}

$svc = Get-Service -Name $ServiceName -ErrorAction SilentlyContinue
if (-not $svc) {
    Write-Host "[info] 서비스 없음: $ServiceName"
    exit 0
}

& nssm stop $ServiceName
& nssm remove $ServiceName confirm
Write-Host "[OK] 제거 완료: $ServiceName"
