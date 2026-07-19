Set-Location D:\Projects\stock-platform
$ErrorActionPreference = "Stop"
$env:PYTHONPATH = "D:\Projects\stock-platform\src"

Write-Output "== alembic current/heads =="
.\.venv\Scripts\python.exe -m alembic current
$heads = .\.venv\Scripts\python.exe -m alembic heads
Write-Output $heads
if (($heads | Measure-Object -Line).Lines -gt 1) {
    throw "Multiple Alembic heads detected"
}

Write-Output "== pytest =="
.\.venv\Scripts\python.exe -m pytest -q --tb=line
if ($LASTEXITCODE -ne 0) {
    throw "pytest failed"
}

Write-Output "== frontend lint/typecheck/test/build =="
Push-Location frontend
try {
    npm run lint
    if ($LASTEXITCODE -ne 0) { throw "frontend lint failed" }
    npm run typecheck
    if ($LASTEXITCODE -ne 0) { throw "frontend typecheck failed" }
    npm run test
    if ($LASTEXITCODE -ne 0) { throw "frontend test failed" }
    npm run build
    if ($LASTEXITCODE -ne 0) { throw "frontend build failed" }
}
finally {
    Pop-Location
}

Write-Output "Release verification passed (backend + frontend)"
