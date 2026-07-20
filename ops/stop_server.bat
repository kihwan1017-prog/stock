@echo off
setlocal EnableExtensions
cd /d "%~dp0"
call "_common.bat"

if exist "%PID_FILE%" (
  set /p PID=<"%PID_FILE%"
  if defined PID (
    echo [stop] PID file: %PID%
    taskkill /PID %PID% /T /F >nul 2>&1
  )
  del /f /q "%PID_FILE%" >nul 2>&1
)

powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$c=Get-NetTCPConnection -LocalPort %API_PORT% -State Listen -EA SilentlyContinue | Select-Object -First 1; ^
   if ($c) { Stop-Process -Id $c.OwningProcess -Force -EA SilentlyContinue; Write-Host ('[stop] killed port %API_PORT% PID=' + $c.OwningProcess); exit 0 } ^
   else { Write-Host '[stop] no listener on port %API_PORT%'; exit 0 }"

echo [OK] stop requested
endlocal
exit /b 0
