# Broker Vault Master Key 생성 (STEP 8-5-2)
# AES-256용 32바이트 난수를 Base64로 파일에 저장한다.
# Key 원문은 콘솔에 출력하지 않는다.

param(
    [string]$OutputPath = "E:\StockTrading\secrets\broker-vault-master.key"
)

$ErrorActionPreference = "Stop"

Write-Host "=== Broker Vault Master Key Generator ==="

$dir = Split-Path -Parent $OutputPath
if (-not (Test-Path -LiteralPath $dir)) {
    New-Item -ItemType Directory -Path $dir -Force | Out-Null
    Write-Host "Created directory: $dir"
}

if (Test-Path -LiteralPath $OutputPath) {
    Write-Host "ERROR: Key file already exists. Refusing to overwrite."
    Write-Host "Path: $OutputPath"
    Write-Host "Rotate manually after backing up the old key."
    exit 1
}

# 프로젝트 Git 경로에 생성 금지
$repoHint = Join-Path $PSScriptRoot ".."
$resolvedOut = (Resolve-Path -LiteralPath $dir).Path
$resolvedRepo = (Resolve-Path -LiteralPath $repoHint).Path
if ($resolvedOut.StartsWith($resolvedRepo, [System.StringComparison]::OrdinalIgnoreCase)) {
    Write-Host "ERROR: Do not create master key inside the Git repository."
    Write-Host "Use E:\StockTrading\secrets\ (or equivalent outside the repo)."
    exit 1
}

$bytes = New-Object byte[] 32
[System.Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($bytes)
$b64 = [Convert]::ToBase64String($bytes)
# 파일에만 기록 — Write-Host 로 원문 출력 금지
[System.IO.File]::WriteAllText($OutputPath, $b64)

# 가능하면 ACL 제한 (현재 사용자 FullControl)
try {
    $acl = Get-Acl -LiteralPath $OutputPath
    $acl.SetAccessRuleProtection($true, $false)
    $rule = New-Object System.Security.AccessControl.FileSystemAccessRule(
        [System.Security.Principal.WindowsIdentity]::GetCurrent().Name,
        "FullControl",
        "Allow"
    )
    $acl.SetAccessRule($rule)
    Set-Acl -LiteralPath $OutputPath -AclObject $acl
    Write-Host "ACL restricted to current user."
} catch {
    Write-Host "WARN: Could not tighten ACL. Restrict NTFS permissions manually."
}

# 메모리 정리 시도
$bytes = $null
$b64 = $null
[GC]::Collect()

Write-Host "Master key file CREATED."
Write-Host "Path: $OutputPath"
Write-Host "Set env: BROKER_VAULT_MASTER_KEY_FILE=$OutputPath"
Write-Host "Backup this file separately from DB backups."
Write-Host "Key material was NOT printed."
exit 0
