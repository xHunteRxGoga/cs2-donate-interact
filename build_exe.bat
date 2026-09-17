@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo Installing build tools...
python -m pip install -r requirements.txt pyinstaller -q
echo.
echo Building CS2DonateInteract.exe ...
python -m PyInstaller --noconfirm build\cs2-donate-interact.spec
if errorlevel 1 (
  echo Build failed.
  pause
  exit /b 1
)
echo.
echo Ready: dist\CS2DonateInteract.exe
echo Copy config.json next to the exe on the buyer PC, set access.server to your API.
pause
