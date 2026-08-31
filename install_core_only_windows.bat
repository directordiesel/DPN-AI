@echo off
setlocal EnableExtensions
cd /d "%~dp0"
title DPN AI v5.0.7 Core-Only Installer
color 0C

powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0INSTALL_DPN_AI.ps1" -SkipModels -SkipVoice
set "DPN_EXIT=%ERRORLEVEL%"
if not "%DPN_EXIT%"=="0" pause
exit /b %DPN_EXIT%