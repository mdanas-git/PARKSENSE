@echo off
title ParkSense Wokwi Cloudflare Tunnel
cd /d "%~dp0"
echo =========================================================
echo       PARKSENSE WOKWI CLOUDFLARE INTEGRATION TUNNEL
echo =========================================================
echo.
if exist tools\tunnel_runner.py (
    python tools\tunnel_runner.py
) else (
    python tunnel_runner.py
)
if errorlevel 1 (
    echo.
    echo Python runner failed, starting cloudflared directly...
    if exist tools\cloudflared.exe (
        tools\cloudflared.exe tunnel --url http://localhost:5000
    ) else (
        cloudflared.exe tunnel --url http://localhost:5000
    )
)
pause
