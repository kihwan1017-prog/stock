@echo off
setlocal EnableExtensions EnableDelayedExpansion
cd /d "%~dp0"
call "_common.bat"
call "_ensure_dirs.bat"

echo [start] project=%PROJECT_ROOT%
echo [start] ops_root=%STOCK_OPS_ROOT%
echo [start] secrets=%SECRETS_ENV%

if not exist "%VENV_UVICORN%" (
  echo [ERROR] uvicorn not found: %VENV_UVICORN%
  echo         Install venv first. See INSTALL.md
  exit /b 1
)

if not exist "%SECRETS_ENV%" (
  echo [WARN] secrets env missing: %SECRETS_ENV%
)

if exist "%PID_FILE%" (
  set /p OLD_PID=<"%PID_FILE%"
  if defined OLD_PID (
    tasklist /FI "PID eq !OLD_PID!" 2>nul | find "!OLD_PID!" >nul
    if not errorlevel 1 (
      echo [ERROR] already running PID=!OLD_PID!
      echo         Run stop_server.bat first.
      exit /b 2
    )
  )
)

for /f "tokens=1-3 delims=/. " %%a in ("%DATE%") do set "D=%%c%%a%%b"
for /f "tokens=1-3 delims=:." %%a in ("%TIME%") do set "T=%%a%%b%%c"
set "T=%T: =0%"
set "STAMP=%D%_%T%"
set "OUT_LOG=%LOG_DIR%\uvicorn_%STAMP%.out.log"
set "ERR_LOG=%LOG_DIR%\uvicorn_%STAMP%.err.log"

echo [start] host=%API_HOST% port=%API_PORT%
echo [start] stdout -^> %OUT_LOG%
echo [start] stderr -^> %ERR_LOG%

powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0_start_api.ps1" -ProjectRoot "%PROJECT_ROOT%" -VenvUvicorn "%VENV_UVICORN%" -PythonPath "%PYTHONPATH%" -ApiHost %API_HOST% -ApiPort %API_PORT% -OutLog "%OUT_LOG%" -ErrLog "%ERR_LOG%" -PidFile "%PID_FILE%" -TimeoutSec 60
if errorlevel 1 (
  echo [ERROR] start failed. Check log: %ERR_LOG%
  exit /b 3
)

echo [OK] started. PID file: %PID_FILE%
echo      health: %HEALTH_URL%
endlocal
exit /b 0
