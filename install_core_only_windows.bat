@echo off
setlocal EnableExtensions
cd /d "%~dp0"
set "DPN_VERSION=unknown"
if exist "VERSION" set /p DPN_VERSION=<"VERSION"
title DPN AI v%DPN_VERSION% Core-Only Installer
color 0C

powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0INSTALL_DPN_AI.ps1" -SkipModels -SkipVoice
set "DPN_EXIT=%ERRORLEVEL%"
if not "%DPN_EXIT%"=="0" pause
exit /b %DPN_EXIT%