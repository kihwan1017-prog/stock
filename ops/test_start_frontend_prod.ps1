#Requires -Version 5.1
<#
.SYNOPSIS
  start_frontend_prod.ps1 focused checks (no backend mutation).
#>
[CmdletBinding()]
param([string]$ProjectRoot = "d:\Projects\stock-platform")

$ErrorActionPreference = "Stop"
$failed = 0
function Ok([bool]$c,[string]$n){ if($c){"PASS $n"} else {"FAIL $n"; $script:failed++} }

$script = Join-Path $ProjectRoot "ops\start_frontend_prod.ps1"
Ok (Test-Path $script) "script_exists"
$raw = Get-Content $script -Raw
Ok ($raw -notmatch '(?m)^\s*(npm run dev|next\s+dev)\b') "no_dev_mode"
Ok ($raw -match 'npm.*run start|npm run start') "uses_start"
Ok ($raw -match 'BUILD_ID|\.next') "requires_build"

# B already running skip
$out = & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $script -ProjectRoot $ProjectRoot 2>&1 | Out-String
Ok ($out -match 'ALREADY_RUNNING') "B_already_running_skip"

# C single listener
$lines = @(netstat -ano | Select-String -Pattern ':3000\s+.*LISTENING')
Ok ($lines.Count -ge 1) "C_listener_present"
# unique PIDs
$pids = @()
foreach ($line in $lines) {
  $parts = ($line.ToString() -split '\s+') | Where-Object { $_ -ne '' }
  if ($parts.Count -ge 5) { $pids += $parts[-1] }
}
$uniq = @($pids | Select-Object -Unique)
Ok ($uniq.Count -eq 1) "C_single_listen_pid"

# E backend not started by this script
Ok ($raw -notmatch 'start_backend|uvicorn|8000') "E_no_backend_coupling"

"FAILED=$failed"
if ($failed -gt 0) { exit 1 }
exit 0
