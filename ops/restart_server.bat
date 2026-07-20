@echo off
setlocal
cd /d "%~dp0"
echo [restart] stop...
call "stop_server.bat"
timeout /t 2 /nobreak >nul
echo [restart] start...
call "start_server.bat"
endlocal
exit /b %ERRORLEVEL%
