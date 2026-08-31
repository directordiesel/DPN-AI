@echo off
setlocal EnableExtensions
cd /d "%~dp0"
title DPN AI Verified Backup
color 0C
if not exist ".venv\Scripts\python.exe" (
  echo DPN AI is not installed. Run install_windows.bat first.
  pause
  exit /b 1
)
call ".venv\Scripts\activate.bat"
python manage.py backup --name "manual-windows-backup" --path "."
pause