@echo off
setlocal EnableExtensions
cd /d "%~dp0"
title DPN AI v5 Upgrade
color 0C

echo ============================================================
echo                 DPN AI v5 UPGRADE
echo ============================================================
echo This upgrades Python dependencies and preserves data, workspace,
echo .env settings, conversations, memories, projects, missions, skills, workflows, and snapshots.
echo.

if not exist ".venv\Scripts\python.exe" (
  echo Existing environment not found. Running full installer instead.
  call install_windows.bat
  exit /b %errorlevel%
)
call ".venv\Scripts\activate.bat"
python -m pip install --upgrade pip setuptools wheel
if errorlevel 1 goto :failed
python -m pip install --upgrade -r requirements.txt
if errorlevel 1 goto :failed
python -m pip install --upgrade -r requirements-voice.txt
if errorlevel 1 echo [WARNING] Voice dependency upgrade did not complete. Run install_voice_windows.bat later.
python manage.py install-voices sentinel aurora
if errorlevel 1 echo [WARNING] Voice model installation did not complete. Run install_voice_windows.bat later.
python -m compileall app
if errorlevel 1 goto :failed
python manage.py doctor

echo.
echo DPN AI v5 upgrade completed. Database migrations run automatically.
pause
exit /b 0
:failed
echo Upgrade failed. Review the error above.
pause
exit /b 1