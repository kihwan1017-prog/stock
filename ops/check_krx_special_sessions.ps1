# STEP 8-5-11 — Pending/Conflict Calendar Change Request 점검
# DB 직접 UPDATE 금지. CLI만 사용.
$ErrorActionPreference = "Stop"
Set-Location (Split-Path -Parent $PSScriptRoot)
python -m stock_platform.operation.krx_calendar_change_cli pending
python -m stock_platform.operation.krx_calendar_change_cli special
