@echo off
title Spatial AI Smart Room - Digital Twin Server
cls
echo ======================================================================
echo   SPATIAL AI SMART ROOM AUTOMATION - PRODUCTION LAUNCHER
echo ======================================================================
echo.

if not exist ".\.venv\Scripts\python.exe" (
    echo [ERROR] Virtual environment not found at .\.venv!
    echo Please install dependencies first.
    pause
    exit /b 1
)

echo [STARTING] Launching Spatial AI Digital Twin Engine...
echo [INFO] Serving dashboard at http://localhost:5000
echo.
".\.venv\Scripts\python.exe" -u spatial_server.py
pause
