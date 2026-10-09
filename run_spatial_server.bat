@echo off
title Spatial AI Smart Room Automation Monitor
cd /d "%~dp0"
echo =====================================================================
echo   Starting Spatial AI Power-Efficient Smart Room Automation Server
echo =====================================================================
echo.
if not exist ".venv\Scripts\python.exe" (
    echo [ERROR] Virtual environment .venv not found!
    pause
    exit /b 1
)

echo Activating virtual environment...
call .venv\Scripts\activate.bat

echo Starting spatial_server.py...
python spatial_server.py

pause
