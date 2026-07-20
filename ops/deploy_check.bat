@echo off
setlocal
cd /d "%~dp0"
call "_common.bat"

echo ============================================================
echo  Deploy check (DB / alembic / health)
echo ============================================================

if not exist "%VENV_PY%" (
  echo [FAIL] venv missing
  exit /b 1
)

echo.
echo [1] DB connection...
set "PYTHONPATH=%PROJECT_ROOT%\src"
"%VENV_PY%" "%PROJECT_ROOT%\scripts\test_db_connection.py"
if errorlevel 1 (
  echo [FAIL] DB
  exit /b 2
)

echo.
echo [2] Alembic...
pushd "%PROJECT_ROOT%"
"%VENV_PY%" -m alembic current
"%VENV_PY%" -m alembic heads
popd

echo.
echo [3] Health...
call "health_check.bat"
if errorlevel 1 (
  echo [WARN] health failed - start server then retry
)

echo.
echo [4] Manual checklist
echo   - Broker: Admin recovery/status
echo   - Telegram: POST /api/v1/notification/test
echo   - Ollama: GET /api/v1/ollama/status
echo   - Scheduler / Kill Switch / Position Monitor
echo   - secrets: %SECRETS_ENV%
echo.
echo See RELEASE_CHECKLIST.md / OPERATIONS.md
endlocal
exit /b 0
