@echo off
setlocal EnableExtensions
cd /d "%~dp0"
title DPN AI v5 Voice Installer
color 0C
if not exist ".venv\Scripts\python.exe" (
  echo [ERROR] Run install_windows.bat first.
  pause
  exit /b 1
)
echo ============================================================
echo       DPN AI v5 - LOCAL SENTINEL AND AURORA VOICES
echo ============================================================
echo Installing Piper neural speech, faster-whisper, and fallback TTS...
".venv\Scripts\python.exe" -m pip install -r requirements-voice.txt
if errorlevel 1 goto :failed
echo Downloading the original DPN Sentinel and DPN Aurora voice models...
".venv\Scripts\python.exe" manage.py install-voices sentinel aurora
if errorlevel 1 goto :failed
echo.
echo Voice installation complete. Enable Offline Voice Tools in DPN AI Settings.
pause
exit /b 0
:failed
echo.
echo [ERROR] Voice installation did not complete. Review the message above.
pause
exit /b 1