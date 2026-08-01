@echo off
setlocal EnableExtensions
cd /d "%~dp0"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0ops\dev\restart-dev.ps1"
set "EC=%ERRORLEVEL%"
if not "%EC%"=="0" (
  echo [restart-dev.bat] failed with exit code %EC%
  pause
  exit /b %EC%
)
exit /b 0
