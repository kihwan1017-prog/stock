Set-Location D:\Projects\stock-platform

Write-Output "== alembic current =="
.\.venv\Scripts\python.exe -m alembic current

Write-Output "== alembic heads =="
$heads = .\.venv\Scripts\python.exe -m alembic heads
Write-Output $heads

if (($heads | Measure-Object -Line).Lines -gt 1) {
    Write-Error "Multiple Alembic heads detected"
    exit 1
}

Write-Output "Alembic verification passed"
