@echo off
title Spatial AI Classroom Automation - Training Footage & Digital Twin Monitor
cd /d "%~dp0"
echo =====================================================================
echo   Classroom Training Footage & Real-Time AI Digital Twin Dashboard
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
echo    💻 Local PC URL:    http://localhost:5000
echo    📶 Same Wi-Fi Link: http://10.253.100.7:5000
echo    🎯 Room Calibrate:  http://10.253.100.7:5000/calibrate
echo =====================================================================
echo.
echo Opening Digital Twin Dashboard in browser...
start http://localhost:5000

echo.
echo Starting Spatial AI Detection Server on Classroom Training Footage...
".venv\Scripts\python.exe" -u spatial_server.py "models\Classroom Video\EEE1_classroom.mp4" %*

pause
