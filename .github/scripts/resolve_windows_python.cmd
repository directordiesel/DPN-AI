@echo off
setlocal EnableExtensions

set "PYTHON_EXE="
for /f "delims=" %%P in ('where python 2^>nul') do if not defined PYTHON_EXE set "PYTHON_EXE=%%P"

if not defined PYTHON_EXE if exist "C:\Users\diese\AppData\Local\Programs\Python\Python312\python.exe" set "PYTHON_EXE=C:\Users\diese\AppData\Local\Programs\Python\Python312\python.exe"

if not defined PYTHON_EXE (
  echo ERROR: Python 3.12 was not found on the trusted DPN Windows runner.
  exit /b 1
)

"%PYTHON_EXE%" --version || exit /b 1
"%PYTHON_EXE%" -m pip --version || exit /b 1

for %%D in ("%PYTHON_EXE%") do set "PYTHON_DIR=%%~dpD"

if defined GITHUB_ENV echo PYTHON_EXE=%PYTHON_EXE%>>"%GITHUB_ENV%"
if defined GITHUB_PATH echo %PYTHON_DIR%>>"%GITHUB_PATH%"

echo Resolved trusted Windows Python: %PYTHON_EXE%
exit /b 0
