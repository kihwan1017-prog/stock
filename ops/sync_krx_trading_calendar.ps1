# STEP 8-5-7 — KRX Trading Calendar 초기 Sync
# Usage: .\ops\sync_krx_trading_calendar.ps1
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root
$env:PYTHONPATH = Join-Path $Root "src"

$Python = Join-Path $Root ".venv\Scripts\python.exe"
if (-not (Test-Path $Python)) {
    $Python = "python"
}

Write-Host "Running KRX trading calendar sync..."
& $Python -m stock_platform.operation.sync_krx_calendar_cli @args
if ($LASTEXITCODE -ne 0) {
    throw "Calendar sync failed with exit code $LASTEXITCODE"
}
Write-Host "Done. Verify coverage in Admin market-calendar / health."
