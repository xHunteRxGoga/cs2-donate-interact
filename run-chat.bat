@echo off
chcp 65001 >nul
cd /d "%~dp0"
python -m pip install -r requirements.txt -q
python -m src.chat
if errorlevel 1 pause
