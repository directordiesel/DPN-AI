@echo off
setlocal
cd /d "%~dp0"
if not exist .venv\Scripts\python.exe (
  echo Run install_windows.bat first.
  pause
  exit /b 1
)
echo.
echo DPN AI v5 Optional Capability Installer
echo 1. Browser automation
 echo 2. Desktop automation
 echo 3. Offline voice
 echo 4. MCP tool bridge
 echo 5. All optional capabilities
set /p CHOICE=Choose 1-5: 
if "%CHOICE%"=="1" goto browser
if "%CHOICE%"=="2" goto desktop
if "%CHOICE%"=="3" goto voice
if "%CHOICE%"=="4" goto mcp
if "%CHOICE%"=="5" goto all
echo Invalid choice.
pause
exit /b 1
:browser
.venv\Scripts\python.exe -m pip install -r requirements-browser.txt
.venv\Scripts\python.exe -m playwright install chromium
goto done
:desktop
.venv\Scripts\python.exe -m pip install -r requirements-desktop.txt
goto done
:voice
.venv\Scripts\python.exe -m pip install -r requirements-voice.txt
.venv\Scripts\python.exe manage.py install-voices sentinel aurora
goto done
:mcp
.venv\Scripts\python.exe -m pip install -r requirements-mcp.txt
goto done
:all
.venv\Scripts\python.exe -m pip install -r requirements-browser.txt -r requirements-desktop.txt -r requirements-voice.txt -r requirements-mcp.txt
.venv\Scripts\python.exe -m playwright install chromium
.venv\Scripts\python.exe manage.py install-voices sentinel aurora
:done
echo Optional capability installation finished.
pause