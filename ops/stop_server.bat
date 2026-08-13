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

powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0_stop_port_listener.ps1" -Port %API_PORT% -ProjectRoot "%PROJECT_ROOT%"

echo [OK] stop requested
endlocal
exit /b 0
