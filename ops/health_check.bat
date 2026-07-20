@echo off
setlocal
cd /d "%~dp0"
call "_common.bat"

echo [health] GET %HEALTH_URL%
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "try { $r = Invoke-WebRequest -Uri '%HEALTH_URL%' -UseBasicParsing -TimeoutSec 15; Write-Host ('HTTP ' + [int]$r.StatusCode); Write-Host $r.Content; if ([int]$r.StatusCode -ge 200 -and [int]$r.StatusCode -lt 300) { exit 0 } else { exit 2 } } catch { Write-Host ('[FAIL] ' + $_.Exception.Message); exit 1 }"

set "EC=%ERRORLEVEL%"
if "%EC%"=="0" (
  echo [OK] health check passed
) else (
  echo [FAIL] health check failed exit=%EC%
)
endlocal
exit /b %EC%
