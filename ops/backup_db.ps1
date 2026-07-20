# DB 전체 백업 (pg_dump -Fc)
param(
    [Parameter(Mandatory = $true)][string]$BackupDir,
    [Parameter(Mandatory = $true)][string]$ProjectRoot
)

$ErrorActionPreference = "Stop"
$src = Join-Path $ProjectRoot "src"
if ($env:PYTHONPATH -notlike "*$src*") {
    $env:PYTHONPATH = $src
}

Set-Location $ProjectRoot
$py = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $py)) {
    throw "venv python 없음: $py"
}

# settings 에서 DSN 파싱
$code = @'
from urllib.parse import unquote, urlparse
from stock_platform.common.settings import get_settings
s = get_settings()
p = urlparse(s.database_url)
print(p.hostname or "localhost")
print(p.port or 5432)
print(unquote(p.username or "postgres"))
print(unquote(p.password or ""))
print((p.path or "/postgres").lstrip("/") or "postgres")
'@

$info = & $py -c $code
if ($LASTEXITCODE -ne 0) { throw "settings 로드 실패" }
$hostName = $info[0]
$port = $info[1]
$user = $info[2]
$password = $info[3]
$dbname = $info[4]

if (-not (Get-Command pg_dump -ErrorAction SilentlyContinue)) {
    throw "pg_dump 없음 — PostgreSQL client bin 을 PATH 에 추가하세요."
}

if (-not (Test-Path $BackupDir)) {
    New-Item -ItemType Directory -Path $BackupDir -Force | Out-Null
}

$stamp = Get-Date -Format "yyyyMMdd_HHmmss"
$out = Join-Path $BackupDir "stock_$stamp.dump"
$env:PGPASSWORD = $password

Write-Host "[backup] pg_dump -> $out"
& pg_dump -h $hostName -p $port -U $user -d $dbname -Fc -f $out
if ($LASTEXITCODE -ne 0) {
    throw "pg_dump 실패"
}

# 설정 파일 스냅샷 (비밀 포함 — 백업 폴더 ACL 보호 필요)
$opsRoot = Split-Path $BackupDir -Parent
$secrets = Join-Path $opsRoot "secrets\stock-platform.env"
if (Test-Path $secrets) {
    $secCopy = Join-Path $BackupDir "stock-platform.env.$stamp.bak"
    Copy-Item $secrets $secCopy -Force
    Write-Host "[backup] secrets copy -> $secCopy"
}

Write-Host "[OK] size=$((Get-Item $out).Length) bytes"
exit 0
