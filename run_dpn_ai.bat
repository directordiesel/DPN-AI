@echo off
setlocal EnableExtensions
cd /d "%~dp0"
title DPN AI v5.0.7 Operations Core
color 0C

if not exist "requirements.txt" (
  echo [ERROR] DPN AI release files are missing.
  echo Extract the complete ZIP before launching.
  pause
  exit /b 1
)

if not exist ".venv\Scripts\python.exe" (
  echo DPN AI is not installed or the environment was lost.
  echo Starting the repair-capable installer...
  call repair_windows.bat
  if errorlevel 1 exit /b 1
)

".venv\Scripts\python.exe" -c "import sys; raise SystemExit(0 if sys.version_info >= (3,11) else 1)" >nul 2>&1
if errorlevel 1 (
  echo [WARNING] The Python environment is damaged. Starting repair...
  call repair_windows.bat
  if errorlevel 1 exit /b 1
)

if not exist ".env" copy /Y ".env.example" ".env" >nul
if not exist "runtime_logs" mkdir "runtime_logs"

where ollama >nul 2>&1
if errorlevel 1 (
  echo [WARNING] Ollama is not installed. Configure another compatible model provider or install Ollama later.
) else (
  ollama list >nul 2>&1
  if errorlevel 1 (
    echo Starting local Ollama model service...
    start "DPN AI - Ollama" /min ollama serve
    timeout /t 4 /nobreak >nul
  )
)

echo ============================================================
echo DPN AI v5.0.7 is starting at http://127.0.0.1:8787
echo Press Ctrl+Space in the browser to talk to DPN AI.
echo Close this window to stop the application server.
echo ============================================================
".venv\Scripts\python.exe" launch.py 1>>"runtime_logs\server.log" 2>>&1
set "DPN_EXIT=%ERRORLEVEL%"
if not "%DPN_EXIT%"=="0" (
  echo.
  echo [ERROR] DPN AI stopped with exit code %DPN_EXIT%.
  echo See runtime_logs\server.log for the exact error.
  pause
)
exit /b %DPN_EXIT%