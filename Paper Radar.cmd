@echo off
setlocal
cd /d "%~dp0"
where py >nul 2>&1
if not errorlevel 1 (
    py -3 launch.py
) else (
    python launch.py
)
if errorlevel 1 (
    echo.
    echo Paper Radar could not open. Check the message above.
    echo Python 3.10 or newer must be installed.
    echo Server log: "%~dp0.runtime\launcher-server.log"
    pause
    exit /b 1
)
exit /b 0
