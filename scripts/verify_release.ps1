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

Write-Output "Release verification passed"
