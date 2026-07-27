# STEP 8-5-21 — 검증 DB 생성 + alembic upgrade (슈퍼유저 필요)
param(
    [string]$ProjectRoot = "D:\Projects\stock-platform",
    [string]$AdminUser = "postgres",
    [string]$VerifyDb = "stock_platform_rc_verify",
    [string]$AppUser = ""
)

$ErrorActionPreference = "Stop"
Set-Location $ProjectRoot
$py = Join-Path $ProjectRoot ".venv\Scripts\python.exe"

# 운영 설정의 호스트/포트만 읽고, DB_NAME 은 검증 DB로 오버라이드
$meta = & $py -c @"
from urllib.parse import unquote, urlparse
from stock_platform.common.settings import get_settings
s = get_settings()
p = urlparse(s.database_url)
print(p.hostname or 'localhost')
print(p.port or 5432)
print(unquote(p.username or 'postgres'))
print(unquote(p.password or ''))
print(s.db_user)
"@
$hostName = $meta[0]
$port = $meta[1]
# AdminUser 로 CREATE — 비밀번호는 환경 PGPASSWORD_ADMIN 또는 대화형
if (-not $env:PGPASSWORD_ADMIN) {
    Write-Host "Set PGPASSWORD_ADMIN for superuser before running."
    exit 2
}
$env:PGPASSWORD = $env:PGPASSWORD_ADMIN

$sqlFile = Join-Path $ProjectRoot "ops\create_rc_verify_db.sql"
& psql -h $hostName -p $port -U $AdminUser -d postgres -v ON_ERROR_STOP=1 -f $sqlFile
if ($LASTEXITCODE -ne 0) { throw "create DB failed" }

# 앱 계정으로 upgrade
$env:DB_NAME = $VerifyDb
$env:PGPASSWORD = $meta[3]
& $py -m alembic upgrade head
if ($LASTEXITCODE -ne 0) { throw "alembic upgrade failed" }
& $py -m alembic current
Write-Host "[OK] empty DB upgrade complete: $VerifyDb"
