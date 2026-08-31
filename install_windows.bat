@echo off
setlocal EnableExtensions
cd /d "%~dp0"
title DPN AI v5.0.7 Installer
color 0C

if not exist "INSTALL_DPN_AI.ps1" (
  echo [ERROR] INSTALL_DPN_AI.ps1 is missing.
  echo Right-click the DPN AI ZIP, choose Extract All, and run this file from the extracted folder.
  pause
  exit /b 1
)

powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0INSTALL_DPN_AI.ps1"
set "DPN_EXIT=%ERRORLEVEL%"
if not "%DPN_EXIT%"=="0" (
  echo.
  echo The installer reported an error. Open the newest file in install_logs for the exact cause.
  pause
)
exit /b %DPN_EXIT%