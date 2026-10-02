@echo off
title ParkSense Backend Server
cd /d "%~dp0"
echo =========================================================
echo            PARKSENSE FLASK BACKEND SERVER
echo =========================================================
echo.
echo Starting Flask application on http://127.0.0.1:5000...
echo Serving API and Frontend simultaneously.
echo.
if exist backend\backend.py (
    python backend\backend.py
) else (
    python backend.py
)
if errorlevel 1 (
    echo.
    echo [ERROR] Backend failed to start. Ensure Python 3.9+ and dependencies are installed.
    echo Run: pip install -r requirements.txt
)
pause
