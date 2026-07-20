@echo off
REM Common paths for ops scripts (ASCII only for cmd.exe)

set "OPS_DIR=%~dp0"
pushd "%OPS_DIR%.." >nul
set "PROJECT_ROOT=%CD%"
popd >nul

if not defined STOCK_OPS_ROOT set "STOCK_OPS_ROOT=E:\StockTrading"

set "SECRETS_ENV=%STOCK_OPS_ROOT%\secrets\stock-platform.env"
set "LOG_DIR=%STOCK_OPS_ROOT%\logs"
set "BACKUP_DIR=%STOCK_OPS_ROOT%\backups"
set "DATA_DIR=%STOCK_OPS_ROOT%\data"
set "TEMP_DIR=%STOCK_OPS_ROOT%\temp"
set "CONFIG_DIR=%STOCK_OPS_ROOT%\config"

set "RUN_DIR=%OPS_DIR%run"
set "PID_FILE=%RUN_DIR%\uvicorn.pid"
set "VENV_PY=%PROJECT_ROOT%\.venv\Scripts\python.exe"
set "VENV_UVICORN=%PROJECT_ROOT%\.venv\Scripts\uvicorn.exe"
set "PYTHONPATH=%PROJECT_ROOT%\src"

if not defined API_HOST set "API_HOST=127.0.0.1"
if not defined API_PORT set "API_PORT=8000"
if not defined HEALTH_URL set "HEALTH_URL=http://%API_HOST%:%API_PORT%/health"

exit /b 0
