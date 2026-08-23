@echo off
setlocal
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0start_demo.ps1"
if errorlevel 1 (
    echo.
    echo [ERROR] Startup failed. See the messages above for details.
    pause
)
endlocal
