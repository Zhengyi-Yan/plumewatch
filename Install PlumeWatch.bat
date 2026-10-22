@echo off
setlocal
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0install_windows.ps1"
set "PW_RESULT=%ERRORLEVEL%"
echo.
pause
exit /b %PW_RESULT%
