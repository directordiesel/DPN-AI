@echo off
setlocal EnableExtensions
cd /d "%~dp0"
title DPN AI v5.0.7 Sentinel HD Voice Upgrade
color 0C

echo ============================================================
echo       DPN AI v5.0.7 - SENTINEL HD VOICE UPGRADE
echo ============================================================
echo.
if not exist ".venv\Scripts\python.exe" (
  echo [ERROR] DPN AI virtual environment was not found.
  echo Run repair_windows.bat first.
  pause
  exit /b 1
)

echo Installing or updating local voice support...
".venv\Scripts\python.exe" -m pip install -r requirements-voice.txt
if errorlevel 1 goto :failed

echo.
echo Downloading the cleaner high-quality Sentinel male voice...
".venv\Scripts\python.exe" manage.py install-voices sentinel
if errorlevel 1 goto :failed

echo.
echo Clearing old in-memory voice models on the next restart...
if exist "workspace\generated\voice" echo Existing generated voice files are preserved.
echo.
echo [OK] Sentinel HD is installed.
echo Restart DPN AI, press Ctrl+F5, then choose Sentinel - Clear tone.
pause
exit /b 0

:failed
echo.
echo [ERROR] Sentinel HD could not be installed.
echo Your existing Sentinel voice remains available as a fallback.
echo Check your internet connection and run this file again.
pause
exit /b 1