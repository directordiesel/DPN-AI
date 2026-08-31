@echo off
setlocal EnableExtensions
cd /d "%~dp0"
title DPN AI v5.0.7 Repair
color 0E

if not exist "INSTALL_DPN_AI.ps1" (
  echo [ERROR] INSTALL_DPN_AI.ps1 is missing.
  echo Extract the complete ZIP before running repair.
  pause
  exit /b 1
)

powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0INSTALL_DPN_AI.ps1" -Repair
set "DPN_EXIT=%ERRORLEVEL%"
if not "%DPN_EXIT%"=="0" (
  echo.
  echo Repair did not finish. Open the newest file in install_logs for the exact cause.
  pause
)
exit /b %DPN_EXIT%