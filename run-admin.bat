@echo off
chcp 65001 >nul
cd /d "%~dp0"
net session >nul 2>&1
if %errorLevel% == 0 goto run
echo Нужны права администратора, чтобы клавиши доходили до CS2.
powershell -NoProfile -Command "Start-Process -FilePath '%~f0' -WorkingDirectory '%~dp0' -Verb RunAs"
exit /b
:run
echo Installing dependencies...
python -m pip install -r requirements.txt
echo.
echo Starting CS2 Donate Interact as administrator...
python -m src.main
if errorlevel 1 pause
