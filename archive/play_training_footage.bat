@echo off
title Classroom Training Footage - 24MB YOLO Detection Player
cd /d "%~dp0"
echo =====================================================================
echo   Playing Classroom Training Footage with Fine-Tuned 24MB YOLO Model
echo =====================================================================
echo.
if not exist ".venv\Scripts\python.exe" (
    echo [ERROR] Virtual environment .venv not found!
    pause
    exit /b 1
)

echo.
echo =====================================================================
echo 🌐 DIGITAL TWIN DASHBOARD:
echo    💻 Local PC URL:   http://localhost:5000
echo    📶 Same Wi-Fi Link: http://10.253.100.7:5000
echo =====================================================================
echo.
echo Opening Digital Twin Dashboard in browser...
start http://localhost:5000
echo.
echo Starting Player...
echo Controls: [SPACE] Pause/Play ^| [F] +5s ^| [R] -5s ^| [S] Screenshot ^| [Q] Quit
echo.
".venv\Scripts\python.exe" scripts\play_training_footage.py %*
pause
