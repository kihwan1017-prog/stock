# stop/restart ops script smoke (pytest 없이 로컬 검증용)
#Requires -Version 5.1
$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$opsDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$stopPs1 = Join-Path $opsDir "_stop_port_listener.ps1"
$startPs1 = Join-Path $opsDir "_start_api.ps1"

foreach ($path in @($stopPs1, $startPs1, (Join-Path $opsDir "stop_server.bat"))) {
    if (-not (Test-Path -LiteralPath $path)) {
        throw "missing ops script: $path"
    }
}

# idempotent: 리스너 없을 때 exit 0
& $stopPs1 -Port 59999 -ProjectRoot (Resolve-Path (Join-Path $opsDir "..")).Path | Out-Null
if ($LASTEXITCODE -ne 0) {
    throw "stop_port_listener idempotent check failed exit=$LASTEXITCODE"
}

Write-Host "[OK] ops stop script smoke passed"
exit 0
