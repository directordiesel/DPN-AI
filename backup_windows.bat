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

echo [1/2] Creating verified workspace snapshot...
python manage.py backup --name "manual-windows-backup" --path "."
if errorlevel 1 (
  echo Workspace backup failed. Database backup was not attempted.
  pause
  exit /b 1
)

echo [2/2] Creating atomic verified SQLite backup...
python manage.py db-backup --name "manual-windows-database"
if errorlevel 1 (
  echo Database backup failed.
  pause
  exit /b 1
)

echo DPN AI workspace and database backups completed successfully.
pause
