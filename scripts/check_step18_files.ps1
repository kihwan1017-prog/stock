$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent $PSScriptRoot

$requiredFiles = @(
    "src\stock_platform\brokers\kiwoom\auth.py",
    "src\stock_platform\brokers\kiwoom\client.py",
    "src\stock_platform\collectors\kiwoom\daily_collector.py",
    "src\stock_platform\collectors\kiwoom\parser.py",
    "src\stock_platform\collectors\kiwoom\sync_service.py",
    "src\stock_platform\markets\models.py",
    "src\stock_platform\markets\repository.py",
    "src\stock_platform\markets\service.py",
    "src\stock_platform\api\v1\sync.py"
)

Write-Host "[STEP18 파일 확인]"

$missing = @()

foreach ($relativePath in $requiredFiles) {
    $fullPath = Join-Path $projectRoot $relativePath
    $exists = Test-Path $fullPath

    if (-not $exists) {
        $missing += $relativePath
    }

    [PSCustomObject]@{
        File   = $relativePath
        Exists = $exists
    }
}

if ($missing.Count -gt 0) {
    Write-Host ""
    Write-Error "누락 파일이 있습니다: $($missing -join ', ')"
}

Write-Host ""
Write-Host "필수 파일이 모두 존재합니다."
