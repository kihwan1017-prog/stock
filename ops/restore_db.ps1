# pg_restore (--clean --if-exists)
param(
    [Parameter(Mandatory = $true)][string]$DumpFile,
    [Parameter(Mandatory = $true)][string]$ProjectRoot
)

$ErrorActionPreference = "Stop"
$env:PYTHONPATH = Join-Path $ProjectRoot "src"
Set-Location $ProjectRoot
$py = Join-Path $ProjectRoot ".venv\Scripts\python.exe"

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

if (-not (Get-Command pg_restore -ErrorAction SilentlyContinue)) {
    throw "pg_restore 없음 — PostgreSQL client bin 을 PATH 에 추가하세요."
}
if (-not (Test-Path $DumpFile)) {
    throw "덤프 없음: $DumpFile"
}

$env:PGPASSWORD = $password
Write-Host "[restore] pg_restore --clean --if-exists <- $DumpFile"
& pg_restore -h $hostName -p $port -U $user -d $dbname --clean --if-exists $DumpFile
# pg_restore 는 일부 경고에도 non-zero 를 줄 수 있음 — 치명적 오류만 실패 처리
if ($LASTEXITCODE -gt 1) {
    throw "pg_restore 실패 code=$LASTEXITCODE"
}

Write-Host "[restore] alembic current"
& $py -m alembic current
Write-Host "[OK] restore finished"
exit 0
