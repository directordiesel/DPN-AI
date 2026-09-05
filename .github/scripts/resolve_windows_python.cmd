@echo off
setlocal EnableExtensions EnableDelayedExpansion

set "PYTHON_EXE="
set "PYTHON_VERSION=3.12.10"
set "PYTHON_ARCHIVE_SHA256=8649692de846c56a7189d6dae5c322ab20deb1b5908b6f39426b62a36f39415d"
set "PYTHON_ARCHIVE_URL=https://www.python.org/ftp/python/3.12.10/python-3.12.10-amd64.zip"

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

if not defined PYTHON_EXE call :bootstrap_python
if errorlevel 1 exit /b 1

"%PYTHON_EXE%" --version || exit /b 1
"%PYTHON_EXE%" -m pip --version || exit /b 1

for %%D in ("%PYTHON_EXE%") do set "PYTHON_DIR=%%~dpD"

if defined GITHUB_ENV echo PYTHON_EXE=%PYTHON_EXE%>>"%GITHUB_ENV%"
if defined GITHUB_PATH echo %PYTHON_DIR%>>"%GITHUB_PATH%"

echo Resolved trusted Windows Python: %PYTHON_EXE%
exit /b 0

:bootstrap_python
if not defined RUNNER_TEMP (
  echo ERROR: RUNNER_TEMP is unavailable; refusing an uncontrolled runtime bootstrap.
  exit /b 1
)

where curl.exe >nul 2>&1 || (
  echo ERROR: curl.exe is required to bootstrap the pinned Python runtime.
  exit /b 1
)
where certutil.exe >nul 2>&1 || (
  echo ERROR: certutil.exe is required to verify the Python archive.
  exit /b 1
)
where tar.exe >nul 2>&1 || (
  echo ERROR: tar.exe is required to extract the Python archive.
  exit /b 1
)

set "PYTHON_ROOT=%RUNNER_TEMP%\dpn-python-%PYTHON_VERSION%"
set "PYTHON_ARCHIVE=%RUNNER_TEMP%\python-%PYTHON_VERSION%-amd64.zip"

if exist "%PYTHON_ROOT%\python.exe" (
  set "PYTHON_EXE=%PYTHON_ROOT%\python.exe"
  "%PYTHON_EXE%" -m pip --version >nul 2>&1 && exit /b 0
  rmdir /s /q "%PYTHON_ROOT%"
)

if exist "%PYTHON_ARCHIVE%" del /f /q "%PYTHON_ARCHIVE%"
curl.exe --fail --location --retry 3 --proto "=https" --tlsv1.2 "%PYTHON_ARCHIVE_URL%" --output "%PYTHON_ARCHIVE%" || (
  echo ERROR: Failed to download the pinned Python runtime from python.org.
  exit /b 1
)

set "PYTHON_HASH="
for /f "tokens=1" %%H in ('certutil.exe -hashfile "%PYTHON_ARCHIVE%" SHA256 ^| findstr /R /I "^[0-9a-f][0-9a-f]*$"') do if not defined PYTHON_HASH set "PYTHON_HASH=%%H"
if not defined PYTHON_HASH (
  echo ERROR: Could not calculate the Python archive SHA-256.
  del /f /q "%PYTHON_ARCHIVE%" >nul 2>&1
  exit /b 1
)
if /I not "%PYTHON_HASH%"=="%PYTHON_ARCHIVE_SHA256%" (
  echo ERROR: Python archive SHA-256 verification failed.
  del /f /q "%PYTHON_ARCHIVE%" >nul 2>&1
  exit /b 1
)

if exist "%PYTHON_ROOT%" rmdir /s /q "%PYTHON_ROOT%"
mkdir "%PYTHON_ROOT%" || exit /b 1
tar.exe -xf "%PYTHON_ARCHIVE%" -C "%PYTHON_ROOT%" || (
  echo ERROR: Failed to extract the verified Python runtime.
  exit /b 1
)

set "PYTHON_EXE=%PYTHON_ROOT%\python.exe"
if not exist "%PYTHON_EXE%" (
  echo ERROR: Verified Python archive did not contain python.exe.
  exit /b 1
)

"%PYTHON_EXE%" -m pip --version >nul 2>&1 || "%PYTHON_EXE%" -m ensurepip --upgrade || (
  echo ERROR: The verified Python runtime could not initialize pip.
  exit /b 1
)
"%PYTHON_EXE%" -m pip --version || exit /b 1

echo Bootstrapped verified Python %PYTHON_VERSION% into RUNNER_TEMP.
exit /b 0
