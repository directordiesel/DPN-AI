@echo off
setlocal EnableExtensions
cd /d "%~dp0"
title DPN AI v5.0.7 Diagnostics
color 0E

if not exist ".venv\Scripts\python.exe" (
  echo [WARNING] The DPN AI environment is missing. Starting repair first...
  call repair_windows.bat
  if errorlevel 1 exit /b 1
)
if not exist "install_logs" mkdir "install_logs"
for /f "tokens=1-4 delims=/ " %%a in ("%date%") do set DPN_DATE=%%d%%b%%c
set DPN_TIME=%time::=%
set DPN_TIME=%DPN_TIME:.=%
set DPN_TIME=%DPN_TIME: =0%
set "DPN_REPORT=install_logs\manual_doctor_%DPN_DATE%_%DPN_TIME%.json"

".venv\Scripts\python.exe" manage.py doctor > "%DPN_REPORT%"
set "DPN_EXIT=%ERRORLEVEL%"
type "%DPN_REPORT%"
echo.
echo Diagnostic report saved to %DPN_REPORT%
pause
exit /b %DPN_EXIT%