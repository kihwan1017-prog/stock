#Requires -Version 5.1
<#
.SYNOPSIS
  개발용 Backend/Frontend만 PID 기반으로 종료 (무차별 kill 금지)
#>
[CmdletBinding()]
param(
    [string]$ProjectRoot = "",
    [int]$BackendPort = 8000,
    [int]$FrontendPort = 3000,
    [int]$GraceSec = 15
)

$ErrorActionPreference = "Continue"
Set-StrictMode -Version Latest

function Write-Step([string]$Message) {
    Write-Host "[stop-dev] $Message"
}

function Read-PidFile([string]$Path) {
    if (-not (Test-Path -LiteralPath $Path)) { return $null }
    $raw = (Get-Content -LiteralPath $Path -Raw -ErrorAction SilentlyContinue)
    if ([string]::IsNullOrWhiteSpace($raw)) { return $null }
    $value = $raw.Trim()
    if ($value -match "^\d+$") { return [int]$value }
    return $null
}

function Get-ListenerPid([int]$Port) {
    try {
        $conn = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue |
            Select-Object -First 1
        if ($null -ne $conn -and $conn.OwningProcess -gt 0) {
            return [int]$conn.OwningProcess
        }
    } catch {}
    return $null
}

function Get-ProcessCommandLine([int]$ProcessId) {
    try {
        $proc = Get-CimInstance Win32_Process -Filter "ProcessId=$ProcessId" -ErrorAction Stop
        if ($null -eq $proc) { return "" }
        if ($null -eq $proc.CommandLine) { return "" }
        return [string]$proc.CommandLine
    } catch {
        return ""
    }
}

function Test-DevOwnedProcess([int]$ProcessId, [string]$ProjectRootPath) {
    # postgres 등 외부 프로세스를 listen.pid 오기록으로 죽이지 않기 위한 가드
    $commandLine = ""
    $commandLine = Get-ProcessCommandLine -ProcessId $ProcessId
    if ([string]::IsNullOrWhiteSpace($commandLine)) { return $false }
    $root = $ProjectRootPath.TrimEnd("\", "/")
    $rootAlt = $root -replace "\\", "/"
    if ($commandLine -like "*$root*" -or $commandLine -like "*$rootAlt*") { return $true }
    if ($commandLine -match 'uvicorn|stock_platform|npm run dev|next(-|\s)|node\.exe|start-dev\.ps1') { return $true }
    return $false
}

function Stop-TreeGraceful([int]$ProcessId, [string]$Label, [int]$GraceSeconds) {
    if ($ProcessId -le 0) {
        Write-Step ("{0}: invalid PID - skip" -f $Label)
        return
    }
    try {
        Get-Process -Id $ProcessId -ErrorAction Stop | Out-Null
    } catch {
        Write-Step ("{0}: PID {1} already stopped" -f $Label, $ProcessId)
        return
    }

    Write-Step ("{0}: graceful stop PID={1} (tree)" -f $Label, $ProcessId)
    & taskkill.exe /PID $ProcessId /T 2>$null | Out-Null

    $deadline = (Get-Date).AddSeconds($GraceSeconds)
    while ((Get-Date) -lt $deadline) {
        try {
            Get-Process -Id $ProcessId -ErrorAction Stop | Out-Null
            Start-Sleep -Milliseconds 500
        } catch {
            Write-Step ("{0}: stopped gracefully" -f $Label)
            return
        }
    }

    Write-Step ("{0}: still alive - force stop PID={1}" -f $Label, $ProcessId)
    & taskkill.exe /PID $ProcessId /T /F 2>$null | Out-Null
    Start-Sleep -Milliseconds 400
    try {
        Get-Process -Id $ProcessId -ErrorAction Stop | Out-Null
        Write-Step ("{0}: WARNING process still present after force" -f $Label)
    } catch {
        Write-Step ("{0}: force-stopped" -f $Label)
    }
}

if ([string]::IsNullOrWhiteSpace($ProjectRoot)) {
    $ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
}
$ProjectRoot = $ProjectRoot.TrimEnd("\", "/")
$RunDir = Join-Path $ProjectRoot ".run"
$BackendPidFile = Join-Path $RunDir "backend.pid"
$FrontendPidFile = Join-Path $RunDir "frontend.pid"
$BackendListenPidFile = Join-Path $RunDir "backend.listen.pid"
$FrontendListenPidFile = Join-Path $RunDir "frontend.listen.pid"
$LockFile = Join-Path $RunDir "start-dev.lock"

Write-Step "project=$ProjectRoot"

$targets = @()

$fePid = Read-PidFile $FrontendPidFile
$bePid = Read-PidFile $BackendPidFile
$feListenFile = Read-PidFile $FrontendListenPidFile
$beListenFile = Read-PidFile $BackendListenPidFile
$feListen = Get-ListenerPid $FrontendPort
$beListen = Get-ListenerPid $BackendPort

function Add-StopTarget([string]$Label, $ProcessId, [bool]$RequireDevOwned) {
    if ($null -eq $ProcessId) { return }
    $pidValue = [int]$ProcessId
    if ($RequireDevOwned -and -not (Test-DevOwnedProcess -ProcessId $pidValue -ProjectRootPath $ProjectRoot)) {
        Write-Step ("{0}: PID {1} is not a stock-platform dev process — skip (safety)" -f $Label, $pidValue)
        return
    }
    $script:targets += @{ Label = $Label; Pid = $pidValue }
}

# launcher PID 우선 (taskkill /T 로 자식 uvicorn/node 포함 종료)
Add-StopTarget "frontend-launcher" $fePid $false
Add-StopTarget "backend-launcher" $bePid $false
# listen.pid 는 오기록(예: postgres) 가능성이 있어 ownership 검증
Add-StopTarget "frontend-listen-file" $feListenFile $true
Add-StopTarget "backend-listen-file" $beListenFile $true

# PID 파일이 없는데 포트만 살아 있으면 해당 리스너만 종료
$known = @()
foreach ($t in $targets) { $known += $t.Pid }
if ($null -ne $feListen -and ($known -notcontains $feListen)) {
    Write-Step "frontend port $FrontendPort listener PID=$feListen (orphan) — stop listener only"
    Add-StopTarget "frontend-port" $feListen $true
}
if ($null -ne $beListen -and ($known -notcontains $beListen)) {
    Write-Step "backend port $BackendPort listener PID=$beListen (orphan) — stop listener only"
    Add-StopTarget "backend-port" $beListen $true
}

# start-dev.ps1 이 health 대기 중이면 lock 을 잡은 채 남아 restart 를 막음
try {
    $startDevProcs = Get-CimInstance Win32_Process -Filter "Name='powershell.exe'" -ErrorAction SilentlyContinue |
        Where-Object {
            $_.CommandLine -and
            $_.CommandLine -match 'start-dev\.ps1' -and
            (
                $_.CommandLine -like ("*" + $ProjectRoot + "*") -or
                $_.CommandLine -like ("*" + ($ProjectRoot -replace '\\', '/') + "*")
            )
        }
    foreach ($proc in @($startDevProcs)) {
        if ($null -eq $proc) { continue }
        Add-StopTarget "start-dev-orchestrator" $proc.ProcessId $false
    }
} catch {
    Write-Step "start-dev orchestrator scan skipped: $($_.Exception.Message)"
}

if ($targets.Count -eq 0) {
    Write-Step "no backend/frontend PID or listeners — already stopped"
} else {
    # frontend first, then backend, then start-dev orchestrator (lock holder)
    foreach ($t in $targets) {
        if ($t.Label -like "frontend*") {
            Stop-TreeGraceful -ProcessId $t.Pid -Label $t.Label -GraceSeconds $GraceSec
        }
    }
    foreach ($t in $targets) {
        if ($t.Label -like "backend*") {
            Stop-TreeGraceful -ProcessId $t.Pid -Label $t.Label -GraceSeconds $GraceSec
        }
    }
    foreach ($t in $targets) {
        if ($t.Label -like "start-dev*") {
            Stop-TreeGraceful -ProcessId $t.Pid -Label $t.Label -GraceSeconds $GraceSec
        }
    }
}

# PID / lock 파일 정리
foreach ($f in @(
        $BackendPidFile, $FrontendPidFile,
        $BackendListenPidFile, $FrontendListenPidFile,
        $LockFile
    )) {
    if (Test-Path -LiteralPath $f) {
        Remove-Item -LiteralPath $f -Force -ErrorAction SilentlyContinue
        if (-not (Test-Path -LiteralPath $f)) {
            Write-Step "removed $(Split-Path -Leaf $f)"
        } else {
            Write-Step "WARNING could not remove $(Split-Path -Leaf $f) (still locked?)"
        }
    }
}

# 포트 잔여 안내 (무차별 kill 금지)
$leftBe = Get-ListenerPid $BackendPort
$leftFe = Get-ListenerPid $FrontendPort
if ($null -ne $leftBe) {
    Write-Step "NOTE: port $BackendPort still listening PID=$leftBe (not force-killed; stop manually if foreign)"
} else {
    Write-Step "port $BackendPort free"
}
if ($null -ne $leftFe) {
    Write-Step "NOTE: port $FrontendPort still listening PID=$leftFe (not force-killed; stop manually if foreign)"
} else {
    Write-Step "port $FrontendPort free"
}

Write-Step "done"
exit 0
