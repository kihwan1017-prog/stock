@echo off
setlocal EnableExtensions
cd /d "%~dp0"
call "_common.bat"
call "_ensure_dirs.bat"

echo ============================================================
echo  Update: Backup -^> Stop -^> Update -^> Migration -^> Start -^> Health
echo ============================================================
echo.

echo [1/6] Backup...
call "backup_db.bat"
if errorlevel 1 (
  echo [FAIL] backup failed - abort update
  exit /b 1
)

echo.
echo [2/6] Stop...
call "stop_server.bat"

echo.
echo [3/6] Update ^(git pull + pip^)...
pushd "%PROJECT_ROOT%"
git status -sb
git pull
if errorlevel 1 (
  echo [FAIL] git pull failed
  popd
  exit /b 2
)
".\.venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 (
  echo [FAIL] pip install failed
  popd
  exit /b 3
)
popd

echo.
echo [4/6] Migration...
pushd "%PROJECT_ROOT%"
set "PYTHONPATH=%PROJECT_ROOT%\src"
".\.venv\Scripts\python.exe" -m alembic upgrade head
if errorlevel 1 (
  echo [FAIL] alembic upgrade failed
  popd
  exit /b 4
)
".\.venv\Scripts\python.exe" -m alembic current
popd

echo.
echo [5/6] Start...
call "start_server.bat"
if errorlevel 1 (
  echo [FAIL] start failed
  exit /b 5
)

echo.
echo [6/6] Health...
timeout /t 3 /nobreak >nul
call "health_check.bat"
if errorlevel 1 (
  echo [FAIL] health failed - see OPERATIONS.md
  exit /b 6
)

echo.
echo [OK] update complete
endlocal
exit /b 0
