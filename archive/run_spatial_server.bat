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

echo.
echo =====================================================================
echo 🌐 DIGITAL TWIN DASHBOARD:
echo    💻 Local PC URL:   http://localhost:5000
echo    📶 Same Wi-Fi Link: http://10.253.100.7:5000
echo    🎯 Room Calibrate: http://10.253.100.7:5000/calibrate
echo =====================================================================
echo.
echo Opening Digital Twin Web Dashboard in default browser...
start http://localhost:5000

echo Starting spatial_server.py with Live Web Stream...
".venv\Scripts\python.exe" -u spatial_server.py %*

pause
