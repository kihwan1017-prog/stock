# STEP 8-5-11 — KRX Calendar Change JSON Import Preview
# Usage: .\ops\import_krx_calendar_changes.ps1 -File path\to\changes.json [-Commit]
param(
    [Parameter(Mandatory = $true)]
    [string]$File,
    [switch]$Commit
)
$ErrorActionPreference = "Stop"
Set-Location (Split-Path -Parent $PSScriptRoot)
$argsList = @(
    "-m", "stock_platform.operation.krx_calendar_change_cli",
    "preview-import", "--file", $File
)
if ($Commit) {
    $argsList += "--commit"
}
python @argsList
