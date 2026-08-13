# stock-platform API uvicorn 기동 (cmd start quoting 회피)
param(
    [Parameter(Mandatory = $true)][string]$ProjectRoot,
    [Parameter(Mandatory = $true)][string]$VenvUvicorn,
    [Parameter(Mandatory = $true)][string]$PythonPath,
    [Parameter(Mandatory = $true)][string]$ApiHost,
    [Parameter(Mandatory = $true)][int]$ApiPort,
    [Parameter(Mandatory = $true)][string]$OutLog,
    [Parameter(Mandatory = $true)][string]$ErrLog,
    [Parameter(Mandatory = $true)][string]$PidFile,
    [int]$TimeoutSec = 60
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

if (-not (Test-Path -LiteralPath $VenvUvicorn)) {
    Write-Error "uvicorn not found: $VenvUvicorn"
    exit 1
}

foreach ($logPath in @($OutLog, $ErrLog)) {
    $logDir = Split-Path -Parent $logPath
    if ($logDir -and -not (Test-Path -LiteralPath $logDir)) {
        New-Item -ItemType Directory -Path $logDir -Force | Out-Null
    }
}

Write-Host "[start] launching uvicorn on ${ApiHost}:${ApiPort}"

$innerCmd = (
    "set PYTHONPATH={0} && ""{1}"" stock_platform.api.main:app --host {2} --port {3} --app-dir src" -f
    $PythonPath,
    $VenvUvicorn,
    $ApiHost,
    $ApiPort
)

Start-Process -FilePath "cmd.exe" `
    -ArgumentList @("/c", $innerCmd) `
    -WorkingDirectory $ProjectRoot `
    -WindowStyle Hidden `
    -RedirectStandardOutput $OutLog `
    -RedirectStandardError $ErrLog | Out-Null

& "$PSScriptRoot\_wait_and_write_pid.ps1" -Port $ApiPort -PidFile $PidFile -TimeoutSec $TimeoutSec
exit $LASTEXITCODE
