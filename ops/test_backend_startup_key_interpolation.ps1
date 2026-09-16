#Requires -Version 5.1
<#
.SYNOPSIS
  Backend startup $key outer-expansion boundary tests (WRK-138 / V2).
#>
[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest
$failed = 0
$ProjectRoot = Split-Path -Parent $PSScriptRoot
if ((Split-Path -Leaf $PSScriptRoot) -ieq "ops") {
    $ProjectRoot = Split-Path -Parent $PSScriptRoot
}

function Assert-True([bool]$Cond, [string]$Name) {
    if ($Cond) { Write-Host "PASS $Name" }
    else { Write-Host "FAIL $Name"; $script:failed++ }
}

# A: expandable @" "@ + bare $key in COMMENT → StrictMode fail (defect signature)
$caught = $false
try {
    $null = @"
# (Env:+$key) bare in comment
Remove-Item -LiteralPath ('Env:' + `$key) -ErrorAction SilentlyContinue
"@
} catch {
    $caught = ($_.FullyQualifiedErrorId -eq "VariableIsUndefined")
}
Assert-True $caught "A_outer_expandable_comment_key_fails"

# A2: single-quoted here-string keeps $key literal (no outer expansion)
$literalOk = $true
try {
    $t = @'
foreach ($key in @("X")) {
    # (Env:+$key) comment ok
    Remove-Item -LiteralPath ('Env:' + $key) -ErrorAction SilentlyContinue
}
'@
    if (-not $t.Contains('$key')) { $literalOk = $false }
} catch {
    $literalOk = $false
}
Assert-True $literalOk "A_single_quoted_no_outer_expansion"

# B+C+D: child process StrictMode + multi env remove + no undefined $key
$childProbe = Join-Path $ProjectRoot ".run\test_key_interp_child.ps1"
$probeBody = @'
Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
$keys = @("TEST_STOCK_KEY_A", "TEST_STOCK_KEY_B", "TEST_STOCK_KEY_C")
foreach ($k in $keys) { Set-Item -Path ("Env:" + $k) -Value "1" }
foreach ($key in $keys) {
    if ($key -notmatch "^[A-Za-z_][A-Za-z0-9_]*$") { throw "bad" }
    Remove-Item -LiteralPath ('Env:' + $key) -ErrorAction SilentlyContinue
}
foreach ($k in $keys) {
    if (Test-Path -Path ("Env:" + $k)) { throw "still_set:$k" }
}
Write-Host "CHILD_PROBE_OK"
'@
[System.IO.File]::WriteAllText($childProbe, $probeBody, (New-Object System.Text.UTF8Encoding $false))
$out = & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $childProbe 2>&1
$exit = $LASTEXITCODE
Assert-True (($exit -eq 0) -and ("$out" -match "CHILD_PROBE_OK")) "B_C_D_child_strictmode_multi_env"

# E: start_backend_prod.ps1 uses @' child template + -File (not expandable -Command with $key)
$prod = Join-Path $ProjectRoot "ops\start_backend_prod.ps1"
$raw = Get-Content -LiteralPath $prod -Raw
Assert-True ($raw -match 'backend_prod_child\.ps1') "E_prod_writes_child_file"
Assert-True ($raw -match '-File", \$childScriptPath') "E_prod_uses_File_not_Command"
Assert-True ($raw -match '(?s)\$childTemplate = @''') "E_prod_single_quoted_template"
Assert-True ($raw -notmatch '(?s)\$backendCmd = @"') "E_prod_no_expandable_backendCmd"
# expandable @" block must not contain bare $key (excluding backtick-escaped)
$expandBad = $false
if ($raw -match '(?s)=\s*@"(?<body>.*?)"@') {
    # any remaining expandable blocks: flag bare $key
    $matchesAll = [regex]::Matches($raw, '(?s)=\s*@"(?<body>.*?)"@')
    foreach ($m in $matchesAll) {
        $body = $m.Groups["body"].Value
        foreach ($line in ($body -split "`n")) {
            if ($line -match '\$key' -and $line -notmatch '`\$key') { $expandBad = $true }
        }
    }
}
Assert-True (-not $expandBad) "E_no_bare_key_in_expandable_blocks"

$prodTokens = $null; $prodErrs = $null
$null = [System.Management.Automation.Language.Parser]::ParseFile($prod, [ref]$prodTokens, [ref]$prodErrs)
Assert-True (($null -eq $prodErrs) -or (@($prodErrs).Count -eq 0)) "E_prod_parse_zero"

# F: start-dev same pattern
$dev = Join-Path $ProjectRoot "ops\dev\start-dev.ps1"
$devRaw = Get-Content -LiteralPath $dev -Raw
Assert-True ($devRaw -match 'backend_dev_child\.ps1') "F_dev_child_file"
Assert-True ($devRaw -match '-File", \$childScriptPath') "F_dev_uses_File"
Assert-True ($devRaw -match '(?s)\$childTemplate = @''') "F_dev_single_quoted_template"
Assert-True ($devRaw -notmatch '(?s)\$backendCmd = @"') "F_dev_no_expandable_backendCmd"
$devTokens = $null; $devErrs = $null
$null = [System.Management.Automation.Language.Parser]::ParseFile($dev, [ref]$devTokens, [ref]$devErrs)
Assert-True (($null -eq $devErrs) -or (@($devErrs).Count -eq 0)) "F_dev_parse_zero"

# Simulate outer construction of prod child template under StrictMode (no uvicorn)
$simOk = $true
try {
    $tmpl = @'
foreach ($key in @("GLOBAL_LIVE_ORDER_ENABLED")) {
    Remove-Item -LiteralPath ('Env:' + $key) -ErrorAction SilentlyContinue
}
& "__VENV_PYTHON__" -m uvicorn dummy
'@
    $body = $tmpl.Replace("__VENV_PYTHON__", "C:\fake\python.exe")
    if ($body -match "__[A-Z0-9_]+__") { throw "placeholder left" }
} catch {
    $simOk = $false
    Write-Host "SIM_ERR=$($_.Exception.Message)"
}
Assert-True $simOk "E_strictmode_template_build"

Write-Host "FAILED_COUNT=$failed"
if ($failed -gt 0) { exit 1 }
exit 0
