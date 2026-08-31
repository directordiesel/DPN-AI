@echo off
setlocal
cd /d "%~dp0"
title DPN AI v5 MCP Installer
if not exist .venv\Scripts\python.exe (
  echo Run install_windows.bat first.
  pause
  exit /b 1
)
echo Installing the stable DPN AI MCP client bridge...
.venv\Scripts\python.exe -m pip install -r requirements-mcp.txt
if errorlevel 1 (
  echo [ERROR] MCP installation failed.
  pause
  exit /b 1
)
echo MCP bridge installed. Enable it in System Settings, then configure servers from MCP Tool Bridge.
pause