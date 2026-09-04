@echo off
setlocal EnableExtensions

set "PYTHON_EXE="

for /f "delims=" %%P in ('where python 2^>nul') do if not defined PYTHON_EXE set "PYTHON_EXE=%%P"

if not defined PYTHON_EXE (
  for /f "delims=" %%P in ('py -3.12 -c "import sys; print(sys.executable)" 2^>nul') do if not defined PYTHON_EXE set "PYTHON_EXE=%%P"
)

if not defined PYTHON_EXE if exist "C:\Program Files\Python312\python.exe" set "PYTHON_EXE=C:\Program Files\Python312\python.exe"
if not defined PYTHON_EXE if exist "C:\Python312\python.exe" set "PYTHON_EXE=C:\Python312\python.exe"
if not defined PYTHON_EXE if exist "C:\Users\diese\AppData\Local\Programs\Python\Python312\python.exe" set "PYTHON_EXE=C:\Users\diese\AppData\Local\Programs\Python\Python312\python.exe"

if not defined PYTHON_EXE (
  for /f "tokens=2,*" %%A in ('reg query "HKLM\SOFTWARE\Python\PythonCore\3.12\InstallPath" /ve 2^>nul ^| findstr /i "REG_SZ"') do if exist "%%Bpython.exe" set "PYTHON_EXE=%%Bpython.exe"
)

if not defined PYTHON_EXE (
  for /f "tokens=2,*" %%A in ('reg query "HKLM\SOFTWARE\WOW6432Node\Python\PythonCore\3.12\InstallPath" /ve 2^>nul ^| findstr /i "REG_SZ"') do if exist "%%Bpython.exe" set "PYTHON_EXE=%%Bpython.exe"
)

if not defined PYTHON_EXE (
  echo ERROR: Python 3.12 was not found through PATH, py launcher, machine install paths, or registry.
  exit /b 1
)

"%PYTHON_EXE%" --version || exit /b 1
"%PYTHON_EXE%" -m pip --version || exit /b 1

for %%D in ("%PYTHON_EXE%") do set "PYTHON_DIR=%%~dpD"

if defined GITHUB_ENV echo PYTHON_EXE=%PYTHON_EXE%>>"%GITHUB_ENV%"
if defined GITHUB_PATH echo %PYTHON_DIR%>>"%GITHUB_PATH%"

echo Resolved trusted Windows Python: %PYTHON_EXE%
exit /b 0
