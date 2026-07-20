@echo off
setlocal
cd /d "%~dp0"
call "_common.bat"
call "_ensure_dirs.bat"

echo [backup] dir=%BACKUP_DIR%
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0backup_db.ps1" -BackupDir "%BACKUP_DIR%" -ProjectRoot "%PROJECT_ROOT%"
set "EC=%ERRORLEVEL%"
if "%EC%"=="0" (
  echo [OK] DB backup done
) else (
  echo [FAIL] DB backup failed exit=%EC%
)
endlocal
exit /b %EC%
