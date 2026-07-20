# 포트 리스닝 프로세스 PID를 파일에 기록
param(
    [Parameter(Mandatory = $true)][int]$Port,
    [Parameter(Mandatory = $true)][string]$PidFile,
    [int]$TimeoutSec = 15
)

$deadline = (Get-Date).AddSeconds($TimeoutSec)
while ((Get-Date) -lt $deadline) {
    $conn = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue |
        Select-Object -First 1
    if ($null -ne $conn -and $conn.OwningProcess -gt 0) {
        $pidValue = $conn.OwningProcess
        $dir = Split-Path -Parent $PidFile
        if (-not (Test-Path $dir)) {
            New-Item -ItemType Directory -Path $dir -Force | Out-Null
        }
        Set-Content -Path $PidFile -Value $pidValue -Encoding ascii -NoNewline
        Write-Host "[OK] listening PID=$pidValue port=$Port"
        exit 0
    }
    Start-Sleep -Milliseconds 500
}

Write-Error "포트 $Port 리스너를 $TimeoutSec 초 내 찾지 못했습니다."
exit 1
