@echo off
setlocal
cd /d "%~dp0"
call "_common.bat"

if "%~1"=="" (
  echo Usage: restore_db.bat ^<dump-file^>
  echo Example: restore_db.bat E:\StockTrading\backups\stock_20260720_120000.dump
  echo WARNING: Stop the server first. Existing data may be overwritten.
  exit /b 1
)

set "DUMP_FILE=%~1"
if not exist "%DUMP_FILE%" (
  echo [ERROR] file not found: %DUMP_FILE%
  exit /b 2
)

echo [WARN] restore will modify DB: %DUMP_FILE%
set /p CONFIRM=Type YES to continue: 
if /I not "%CONFIRM%"=="YES" (
  echo cancelled
  exit /b 3
)

powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0restore_db.ps1" -DumpFile "%DUMP_FILE%" -ProjectRoot "%PROJECT_ROOT%"
set "EC=%ERRORLEVEL%"
if "%EC%"=="0" (
  echo [OK] restore done. Check alembic current and health_check.
) else (
  echo [FAIL] restore failed exit=%EC%
)
endlocal
exit /b %EC%
