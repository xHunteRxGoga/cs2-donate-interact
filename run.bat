@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo Installing dependencies...
python -m pip install -r requirements.txt
echo.
echo Starting CS2 Donate Interact...
python -m src.main
if errorlevel 1 pause
