#Requires -Version 5.1
<#
.SYNOPSIS
  개발용 Backend(FastAPI) + Frontend(Next.js) 통합 기동
#>
[CmdletBinding()]
param(
    [string]$ProjectRoot = "",
    [string]$EnvFile = "",
    [string]$BackendHost = "127.0.0.1",
    [int]$BackendPort = 8000,
    [int]$FrontendPort = 3000,
    [string]$FrontendHost = "0.0.0.0",
    [int]$ReadyTimeoutSec = 90,
    [switch]$NoBrowser
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

function Write-Step([string]$Message) {
    Write-Host "[start-dev] $Message"
}

function Fail-Step([string]$Step, [string]$Message) {
    Write-Host "[FAIL] step=$Step :: $Message" -ForegroundColor Red
    exit 1
}

function Test-PortListening([int]$Port) {
    try {
        $conn = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue |
            Select-Object -First 1
        if ($null -ne $conn -and $conn.OwningProcess -gt 0) {
            return [int]$conn.OwningProcess
        }
    } catch {
        # fallback: netstat
    }
    $lines = netstat -ano | Select-String -Pattern ":$Port\s+.*LISTENING"
    foreach ($line in $lines) {
        $parts = ($line.ToString() -split "\s+") | Where-Object { $_ -ne "" }
        if ($parts.Count -ge 5) {
            return [int]$parts[-1]
        }
    }
    return $null
}

function Test-HttpOk([string]$Url, [int]$TimeoutSec = 3) {
    try {
        $resp = Invoke-WebRequest -Uri $Url -UseBasicParsing -TimeoutSec $TimeoutSec
        return ($resp.StatusCode -ge 200 -and $resp.StatusCode -lt 500)
    } catch {
        return $false
    }
}

function Wait-HttpReady([string]$Url, [int]$TimeoutSec, [string]$Label) {
    $deadline = (Get-Date).AddSeconds($TimeoutSec)
    while ((Get-Date) -lt $deadline) {
        if (Test-HttpOk -Url $Url -TimeoutSec 2) {
            Write-Step "$Label ready: $Url"
            return $true
        }
        Start-Sleep -Milliseconds 800
    }
    return $false
}

function Read-PidFile([string]$Path) {
    if (-not (Test-Path -LiteralPath $Path)) { return $null }
    $raw = (Get-Content -LiteralPath $Path -Raw -ErrorAction SilentlyContinue)
    if ([string]::IsNullOrWhiteSpace($raw)) { return $null }
    $value = $raw.Trim()
    if ($value -match "^\d+$") { return [int]$value }
    return $null
}

function Test-ProcessAlive([int]$ProcessId) {
    try {
        $p = Get-Process -Id $ProcessId -ErrorAction Stop
        return $null -ne $p
    } catch {
        return $false
    }
}

# --- paths ---
if ([string]::IsNullOrWhiteSpace($ProjectRoot)) {
    $ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
}
$ProjectRoot = $ProjectRoot.TrimEnd("\", "/")

$VenvPython = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
$FrontendDir = Join-Path $ProjectRoot "frontend"
$RunDir = Join-Path $ProjectRoot ".run"
$LogDir = Join-Path $ProjectRoot "logs\dev"
$BackendPidFile = Join-Path $RunDir "backend.pid"
$FrontendPidFile = Join-Path $RunDir "frontend.pid"
$LockFile = Join-Path $RunDir "start-dev.lock"
$BackendLog = Join-Path $LogDir "backend.log"
$FrontendLog = Join-Path $LogDir "frontend.log"

if ([string]::IsNullOrWhiteSpace($EnvFile)) {
    if ($env:STOCK_PLATFORM_ENV_FILE -and (Test-Path -LiteralPath $env:STOCK_PLATFORM_ENV_FILE)) {
        $EnvFile = $env:STOCK_PLATFORM_ENV_FILE
    } else {
        $EnvFile = "E:\StockTrading\secrets\stock-platform.env"
    }
}

$BackendUrl = "http://localhost:$BackendPort"
$BackendProbeUrl = "http://127.0.0.1:$BackendPort"
$FrontendUrl = "http://localhost:$FrontendPort"
$FrontendProbeUrl = "http://127.0.0.1:$FrontendPort"
$HealthUrl = "$BackendProbeUrl/health"
$OpsHealthUrl = "$BackendProbeUrl/health/ops"
$SwaggerUrl = "$BackendUrl/docs"
$HealthDisplay = "$BackendUrl/health"
$OpsHealthDisplay = "$BackendUrl/health/ops"

Write-Step "project=$ProjectRoot"

# --- lock (중복 start-dev 방지) ---
New-Item -ItemType Directory -Path $RunDir -Force | Out-Null
New-Item -ItemType Directory -Path $LogDir -Force | Out-Null

$lockStream = $null
try {
    $lockStream = [System.IO.File]::Open(
        $LockFile,
        [System.IO.FileMode]::OpenOrCreate,
        [System.IO.FileAccess]::ReadWrite,
        [System.IO.FileShare]::None
    )
} catch {
    Fail-Step "lock" "다른 start-dev가 실행 중이거나 lock 파일이 잠겨 있습니다: $LockFile"
}

try {
    # --- preflight ---
    if (-not (Test-Path -LiteralPath $ProjectRoot)) {
        Fail-Step "project" "프로젝트 경로 없음: $ProjectRoot"
    }
    if (-not (Test-Path -LiteralPath $VenvPython)) {
        Fail-Step "venv" "venv Python 없음: $VenvPython"
    }
    $nodeCmd = Get-Command node -ErrorAction SilentlyContinue
    $npmCmd = Get-Command npm -ErrorAction SilentlyContinue
    if (-not $nodeCmd) { Fail-Step "node" "node 명령을 찾을 수 없습니다." }
    if (-not $npmCmd) { Fail-Step "npm" "npm 명령을 찾을 수 없습니다." }
    if (-not (Test-Path -LiteralPath $FrontendDir)) {
        Fail-Step "frontend" "frontend 폴더 없음: $FrontendDir"
    }
    if (-not (Test-Path -LiteralPath (Join-Path $FrontendDir "package.json"))) {
        Fail-Step "frontend" "package.json 없음: $FrontendDir"
    }
    if (-not (Test-Path -LiteralPath $EnvFile)) {
        Fail-Step "env" "환경파일 없음: $EnvFile (내용은 출력하지 않음)"
    }
    Write-Step "env file present (path only, contents hidden)"

    # PostgreSQL 서비스 또는 DB SELECT 1
    $pgService = Get-Service -ErrorAction SilentlyContinue |
        Where-Object { $_.Name -match "postgres|pgsql" } |
        Select-Object -First 1
    if ($null -ne $pgService) {
        Write-Step ("postgres service={0} status={1}" -f $pgService.Name, $pgService.Status)
        if ($pgService.Status -ne "Running") {
            Fail-Step "postgres" "PostgreSQL 서비스가 Running이 아닙니다: $($pgService.Name)"
        }
    } else {
        Write-Step "postgres service name not found; will probe DB connection"
    }

    Write-Step "checking database connectivity (no secrets printed)"
    $prevEnvFile = $env:STOCK_PLATFORM_ENV_FILE
    $env:STOCK_PLATFORM_ENV_FILE = $EnvFile
    $env:PYTHONPATH = (Join-Path $ProjectRoot "src")
    $dbProbe = & $VenvPython -c @"
from sqlalchemy import text
from stock_platform.database.session import get_engine
with get_engine().connect() as conn:
    conn.execute(text('SELECT 1'))
print('DB_OK')
"@
    if ($LASTEXITCODE -ne 0 -or ($dbProbe -join "`n") -notmatch "DB_OK") {
        if ($null -ne $prevEnvFile) { $env:STOCK_PLATFORM_ENV_FILE = $prevEnvFile }
        Fail-Step "database" "PostgreSQL 연결 실패 (자격증명/연결정보는 출력하지 않음)"
    }
    Write-Step "database connectivity OK"

    # --- already running? ---
    $existingBackendPid = Read-PidFile $BackendPidFile
    $backendPortPid = Test-PortListening $BackendPort
    $backendReady = Test-HttpOk $HealthUrl
    $startBackend = $true
    if ($backendReady -or ($null -ne $backendPortPid)) {
        Write-Step "backend already listening on port $BackendPort (PID=$backendPortPid) — skip start"
        if ($null -ne $backendPortPid) {
            Set-Content -LiteralPath (Join-Path $RunDir "backend.listen.pid") -Value $backendPortPid -Encoding ascii
        }
        $startBackend = $false
    } elseif ($null -ne $existingBackendPid -and (Test-ProcessAlive $existingBackendPid)) {
        Write-Step "backend PID file alive ($existingBackendPid) but port not ready yet — skip duplicate start"
        $startBackend = $false
    }

    $existingFrontendPid = Read-PidFile $FrontendPidFile
    $frontendPortPid = Test-PortListening $FrontendPort
    $frontendReady = Test-HttpOk $FrontendProbeUrl
    $startFrontend = $true
    if ($frontendReady -or ($null -ne $frontendPortPid)) {
        Write-Step "frontend already listening on port $FrontendPort (PID=$frontendPortPid) — skip start"
        if ($null -ne $frontendPortPid) {
            Set-Content -LiteralPath (Join-Path $RunDir "frontend.listen.pid") -Value $frontendPortPid -Encoding ascii
        }
        $startFrontend = $false
    } elseif ($null -ne $existingFrontendPid -and (Test-ProcessAlive $existingFrontendPid)) {
        Write-Step "frontend PID file alive ($existingFrontendPid) — skip duplicate start"
        $startFrontend = $false
    }

    # --- start backend ---
    if ($startBackend) {
        Write-Step "starting backend (uvicorn reload)"
        # OS/PowerShell process env가 secrets env 파일보다 우선하므로,
        # LIVE 관련 override를 자식 프로세스에서 제거해 env 파일을 공식 source로 둔다.
        # cmd.exe 글로브/따옴표 깨짐 방지: PowerShell 에서 python 을 직접 실행한다.
        $backendCmd = @"
`$ErrorActionPreference='Continue'
Set-Location -LiteralPath '$ProjectRoot'
`$env:STOCK_PLATFORM_ENV_FILE='$EnvFile'
`$env:PYTHONPATH='$(Join-Path $ProjectRoot "src")'
`$liveEnvKeys = @(
    'GLOBAL_LIVE_ORDER_ENABLED',
    'UPBIT_LIVE_ORDER_ENABLED',
    'UPBIT_USE_MOCK',
    'LIVE_OUTBOX_WORKER_ENABLED',
    'LIVE_OUTBOX_WORKER_AUTO_START',
    'KIWOOM_LIVE_ORDER_ENABLED',
    'KIWOOM_USE_MOCK'
)
foreach (`$key in `$liveEnvKeys) {
    Remove-Item -LiteralPath ("Env:" + `$key) -ErrorAction SilentlyContinue
}
Write-Host '[start-dev] LIVE-related process env overrides cleared; env file is source of truth'
# glob 패턴(--reload-exclude tmp_* 등)은 cmd/PowerShell 이 확장하므로 사용하지 않는다.
# --reload-dir src 만으로 루트 tmp_*.txt 감시/인자 오염을 피한다.
cmd.exe /c "`"$VenvPython`" -m uvicorn stock_platform.api.main:app --host $BackendHost --port $BackendPort --reload --reload-dir src --app-dir src >> `"$BackendLog`" 2>&1"
"@
        $backendProc = Start-Process -FilePath "powershell.exe" `
            -ArgumentList @(
                "-NoProfile",
                "-ExecutionPolicy", "Bypass",
                "-Command", $backendCmd
            ) `
            -WorkingDirectory $ProjectRoot `
            -WindowStyle Minimized `
            -PassThru
        Set-Content -LiteralPath $BackendPidFile -Value $backendProc.Id -Encoding ascii
        Write-Step "backend launcher PID=$($backendProc.Id) log=$BackendLog"
    }

    # --- start frontend ---
    if ($startFrontend) {
        Write-Step "starting frontend (npm run dev --hostname $FrontendHost)"
        $frontendCmd = @"
`$ErrorActionPreference='Continue'
Set-Location -LiteralPath '$FrontendDir'
cmd.exe /c "npm run dev -- --hostname $FrontendHost --port $FrontendPort >> `"$FrontendLog`" 2>&1"
"@
        $frontendProc = Start-Process -FilePath "powershell.exe" `
            -ArgumentList @(
                "-NoProfile",
                "-ExecutionPolicy", "Bypass",
                "-Command", $frontendCmd
            ) `
            -WorkingDirectory $FrontendDir `
            -WindowStyle Minimized `
            -PassThru
        Set-Content -LiteralPath $FrontendPidFile -Value $frontendProc.Id -Encoding ascii
        Write-Step "frontend launcher PID=$($frontendProc.Id) log=$FrontendLog"
    }

    # --- wait ready + refresh PID from listener ---
    if (-not (Wait-HttpReady -Url $HealthUrl -TimeoutSec $ReadyTimeoutSec -Label "backend")) {
        Fail-Step "backend-ready" "Backend health 대기 시간 초과: $HealthUrl (log=$BackendLog)"
    }
    $listenBackend = Test-PortListening $BackendPort
    if ($null -ne $listenBackend) {
        Set-Content -LiteralPath (Join-Path $RunDir "backend.listen.pid") -Value $listenBackend -Encoding ascii
        Write-Step "backend listen PID=$listenBackend (launcher PID kept in backend.pid)"
    }

    if (-not (Wait-HttpReady -Url $FrontendProbeUrl -TimeoutSec $ReadyTimeoutSec -Label "frontend")) {
        Fail-Step "frontend-ready" "Frontend HTTP 대기 시간 초과: $FrontendProbeUrl (log=$FrontendLog)"
    }
    $listenFrontend = Test-PortListening $FrontendPort
    if ($null -ne $listenFrontend) {
        Set-Content -LiteralPath (Join-Path $RunDir "frontend.listen.pid") -Value $listenFrontend -Encoding ascii
        Write-Step "frontend listen PID=$listenFrontend (launcher PID kept in frontend.pid)"
    }

    # Ops health (optional)
    if (Test-HttpOk $OpsHealthUrl) {
        Write-Step "ops health OK: $OpsHealthUrl"
    } else {
        Write-Step "ops health not ready yet (non-fatal): $OpsHealthUrl"
    }

    Write-Host ""
    Write-Host "=== DEV READY ===" -ForegroundColor Green
    Write-Host "Frontend:  $FrontendUrl"
    Write-Host "Backend:   $BackendUrl"
    Write-Host "Swagger:   $SwaggerUrl"
    Write-Host "Health:    $HealthDisplay"
    Write-Host "Ops Health:$OpsHealthDisplay"
    Write-Host "PID dir:   $RunDir"
    Write-Host "Log dir:   $LogDir"
    Write-Host ""

    if (-not $NoBrowser) {
        try {
            Start-Process $FrontendUrl | Out-Null
        } catch {
            Write-Step "browser open skipped: $($_.Exception.Message)"
        }
    }
}
finally {
    if ($null -ne $lockStream) {
        $lockStream.Close()
        $lockStream.Dispose()
    }
}

exit 0
