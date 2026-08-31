[CmdletBinding()]
param(
    [switch]$Repair,
    [switch]$SkipModels,
    [switch]$SkipVoice,
    [switch]$NonInteractive
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'

$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $Root
$LogDir = Join-Path $Root 'install_logs'
New-Item -ItemType Directory -Force -Path $LogDir | Out-Null
$Timestamp = Get-Date -Format 'yyyyMMdd_HHmmss'
$LogPath = Join-Path $LogDir "install_$Timestamp.log"
$TranscriptStarted = $false
$ExitCode = 1

function Write-Step([string]$Text) {
    Write-Host "`n[$Text]" -ForegroundColor Cyan
}

function Write-Good([string]$Text) {
    Write-Host "[OK] $Text" -ForegroundColor Green
}

function Write-Warn([string]$Text) {
    Write-Host "[WARNING] $Text" -ForegroundColor Yellow
}

function Ask-YesNo([string]$Prompt, [bool]$DefaultYes = $true) {
    if ($NonInteractive) { return $DefaultYes }
    $suffix = if ($DefaultYes) { '[Y/n]' } else { '[y/N]' }
    $answer = Read-Host "$Prompt $suffix"
    if ([string]::IsNullOrWhiteSpace($answer)) { return $DefaultYes }
    return $answer.Trim().ToLowerInvariant().StartsWith('y')
}

function Invoke-PythonProbe([string]$Command, [object[]]$PrefixArgs, [string]$Label) {
    if (-not (Get-Command $Command -ErrorAction SilentlyContinue)) { return $null }

    $ProbePath = Join-Path $Root 'installer_python_probe.py'
    if (-not (Test-Path $ProbePath -PathType Leaf)) {
        throw "The Python detector is missing: $ProbePath"
    }

    $allArgs = @($PrefixArgs) + @($ProbePath)
    $output = & $Command @allArgs 2>&1
    $nativeExit = $LASTEXITCODE
    $resultLine = $output | Where-Object { "$_" -like 'DPN_PYTHON_OK|*' } | Select-Object -Last 1
    if ($nativeExit -ne 0 -or -not $resultLine) { return $null }

    $parts = "$resultLine".Trim() -split '\|', 4
    if ($parts.Count -ne 4 -or $parts[2] -ne '64') { return $null }
    return [pscustomobject]@{
        Command = $Command
        Args = @($PrefixArgs)
        Label = $Label
        Version = $parts[1]
        Executable = $parts[3]
    }
}

function Find-CompatiblePython {
    # Direct commands are checked first. The standalone probe file avoids the
    # multiline `python -c` quoting bug present in Windows PowerShell 5.1.
    $candidates = @(
        [pscustomobject]@{ Command = 'python'; Args = @(); Label = 'python command' },
        [pscustomobject]@{ Command = 'python3'; Args = @(); Label = 'python3 command' },
        [pscustomobject]@{ Command = 'py'; Args = @('-3'); Label = 'Python launcher default 3.x' },
        [pscustomobject]@{ Command = 'py'; Args = @('-3.14'); Label = 'Python launcher 3.14' },
        [pscustomobject]@{ Command = 'py'; Args = @('-3.13'); Label = 'Python launcher 3.13' },
        [pscustomobject]@{ Command = 'py'; Args = @('-3.12'); Label = 'Python launcher 3.12' },
        [pscustomobject]@{ Command = 'py'; Args = @('-3.11'); Label = 'Python launcher 3.11' }
    )

    foreach ($candidate in $candidates) {
        try {
            $info = Invoke-PythonProbe $candidate.Command $candidate.Args $candidate.Label
            if ($info) { return $info }
        } catch {
            Write-Warn "Python candidate '$($candidate.Label)' could not be checked: $($_.Exception.Message)"
        }
    }
    return $null
}

function Test-VenvPython([string]$Path) {
    if (-not (Test-Path $Path -PathType Leaf)) { return $false }
    & $Path -c "import sys,struct; raise SystemExit(0 if sys.version_info >= (3,11) and struct.calcsize('P')*8 == 64 else 1)" *> $null
    return ($LASTEXITCODE -eq 0)
}

function Install-PipRequirements([string]$PythonPath, [string]$RequirementsPath, [bool]$Required) {
    if (-not (Test-Path $RequirementsPath -PathType Leaf)) {
        if ($Required) { throw "Required dependency file is missing: $RequirementsPath" }
        Write-Warn "Optional dependency file is missing: $RequirementsPath"
        return $false
    }

    & $PythonPath -m pip install --disable-pip-version-check --prefer-binary -r $RequirementsPath
    if ($LASTEXITCODE -eq 0) { return $true }

    Write-Warn "The first dependency installation attempt failed. Retrying without the pip cache..."
    & $PythonPath -m pip install --disable-pip-version-check --no-cache-dir --prefer-binary -r $RequirementsPath
    if ($LASTEXITCODE -eq 0) { return $true }

    if ($Required) { throw "Required Python dependencies could not be installed from $RequirementsPath" }
    return $false
}

function Test-OllamaReady {
    if (-not (Get-Command 'ollama' -ErrorAction SilentlyContinue)) { return $false }
    & ollama list *> $null
    if ($LASTEXITCODE -eq 0) { return $true }

    Write-Host 'Starting the Ollama service...'
    Start-Process -FilePath 'ollama' -ArgumentList 'serve' -WindowStyle Minimized | Out-Null
    foreach ($attempt in 1..12) {
        Start-Sleep -Seconds 1
        & ollama list *> $null
        if ($LASTEXITCODE -eq 0) { return $true }
    }
    return $false
}

function Test-OllamaModel([string]$ModelName) {
    $models = & ollama list 2>$null
    if ($LASTEXITCODE -ne 0) { return $false }
    foreach ($line in $models) {
        if ($line -match ('^' + [regex]::Escape($ModelName) + '\s')) { return $true }
    }
    return $false
}

try {
    try {
        Start-Transcript -Path $LogPath -Force | Out-Null
        $TranscriptStarted = $true
    } catch {
        Write-Warn "Could not start PowerShell transcript logging: $($_.Exception.Message)"
    }

    try { $Host.UI.RawUI.WindowTitle = 'DPN AI v5.0.7 Installer Hotfix' } catch { }
    Clear-Host
    Write-Host '============================================================' -ForegroundColor Red
    Write-Host '       DPN AI v5.0.7 - INSTALLER HOTFIX' -ForegroundColor Red
    Write-Host '============================================================' -ForegroundColor Red
    Write-Host "Install folder: $Root"
    Write-Host "Install log:    $LogPath"
    if ($Repair) { Write-Host 'Mode:           Repair existing installation' -ForegroundColor Yellow }

    Write-Step '1/10 Checking the extracted release'
    $requiredFiles = @('requirements.txt', '.env.example', 'launch.py', 'manage.py', 'app\main.py', 'installer_python_probe.py')
    foreach ($file in $requiredFiles) {
        if (-not (Test-Path (Join-Path $Root $file))) {
            throw "The release is incomplete: '$file' is missing. Right-click the ZIP, choose Extract All, and run the installer from the extracted folder. Do not run it inside the ZIP preview."
        }
    }
    $writeTest = Join-Path $Root ".dpn_write_test_$Timestamp.tmp"
    'DPN AI write test' | Set-Content -Path $writeTest -Encoding UTF8
    Remove-Item $writeTest -Force
    Write-Good 'Release files are complete and the folder is writable.'

    Write-Step '2/10 Finding a compatible 64-bit Python installation'
    $script:PythonInfo = Find-CompatiblePython
    if (-not $script:PythonInfo) {
        throw 'No compatible 64-bit Python 3.11 or newer installation was found. Install 64-bit Python, enable the PATH option, then run repair_windows.bat again.'
    }
    Write-Good "Using Python $($script:PythonInfo.Version): $($script:PythonInfo.Executable)"

    Write-Step '3/10 Checking and repairing the isolated environment'
    $VenvDir = Join-Path $Root '.venv'
    $VenvPython = Join-Path $VenvDir 'Scripts\python.exe'
    if ((Test-Path $VenvDir) -and -not (Test-VenvPython $VenvPython)) {
        $brokenName = ".venv_broken_$Timestamp"
        Write-Warn "The existing .venv is damaged or incompatible. Moving it to $brokenName"
        try {
            Move-Item -Path $VenvDir -Destination (Join-Path $Root $brokenName) -Force
        } catch {
            Write-Warn 'The damaged environment could not be renamed. Removing only .venv; data and workspace files are not touched.'
            Remove-Item -Path $VenvDir -Recurse -Force
        }
    }
    if (-not (Test-VenvPython $VenvPython)) {
        Write-Host 'Creating a fresh .venv...'
        $createArgs = @($script:PythonInfo.Args) + @('-m', 'venv', $VenvDir)
        $pythonCommand = $script:PythonInfo.Command
        & $pythonCommand @createArgs
        if ($LASTEXITCODE -ne 0 -or -not (Test-VenvPython $VenvPython)) {
            throw 'Python could not create the isolated .venv environment.'
        }
    }
    Write-Good 'The isolated Python environment is healthy.'

    Write-Step '4/10 Updating Python package tools'
    & $VenvPython -m ensurepip --upgrade
    if ($LASTEXITCODE -ne 0) { Write-Warn 'ensurepip reported a problem; pip may already be installed.' }
    & $VenvPython -m pip install --disable-pip-version-check --upgrade pip setuptools wheel
    if ($LASTEXITCODE -ne 0) {
        Write-Warn 'Package-tool upgrade failed. Retrying without cache...'
        & $VenvPython -m pip install --disable-pip-version-check --no-cache-dir --upgrade pip setuptools wheel
        if ($LASTEXITCODE -ne 0) { throw 'pip, setuptools, and wheel could not be prepared.' }
    }
    Write-Good 'Python package tools are ready.'

    Write-Step '5/10 Installing required DPN AI dependencies'
    [void](Install-PipRequirements $VenvPython (Join-Path $Root 'requirements.txt') $true)
    Write-Good 'Core dependencies are installed.'

    Write-Step '6/10 Installing optional local voice dependencies'
    if ($SkipVoice) {
        Write-Warn 'Voice dependency installation was skipped by command-line option.'
    } elseif (Ask-YesNo 'Install local speech and voice packages now?' $true) {
        $voiceOk = Install-PipRequirements $VenvPython (Join-Path $Root 'requirements-voice.txt') $false
        if ($voiceOk) { Write-Good 'Voice packages are installed.' }
        else { Write-Warn 'Voice packages did not install. DPN AI core installation will continue; run install_voice_windows.bat later.' }
    } else {
        Write-Warn 'Voice packages skipped. They can be added later.'
    }

    Write-Step '7/10 Creating local folders and configuration'
    foreach ($dir in @('data', 'data\voices', 'data\snapshots', 'data\capability_staging', 'data\capability_backups', 'workspace', 'workspace\generated', 'workspace\uploads', 'plugins', 'skills')) {
        New-Item -ItemType Directory -Force -Path (Join-Path $Root $dir) | Out-Null
    }
    $EnvPath = Join-Path $Root '.env'
    if (-not (Test-Path $EnvPath)) {
        Copy-Item (Join-Path $Root '.env.example') $EnvPath
        Write-Good 'Created a fresh .env configuration.'
    } else {
        Write-Good 'Existing .env configuration was preserved.'
    }

    Write-Step '8/10 Checking the local model service'
    $OllamaInstalled = [bool](Get-Command 'ollama' -ErrorAction SilentlyContinue)
    if (-not $OllamaInstalled) {
        Write-Warn 'Ollama is not installed. DPN AI itself is installed and can use an OpenAI-compatible provider, or Ollama can be installed later.'
        Write-Warn 'Official Ollama Windows installer: https://ollama.com/download/windows'
    } elseif (-not (Test-OllamaReady)) {
        Write-Warn 'Ollama is installed but did not start. Continue installation, restart Windows if needed, then open Ollama before launching DPN AI.'
    } elseif ($SkipModels) {
        Write-Warn 'Model downloads were skipped by command-line option.'
    } else {
        Write-Good 'Ollama is running.'
        $modelsToInstall = @('qwen3.5:9b', 'nomic-embed-text')
        foreach ($model in $modelsToInstall) {
            if (Test-OllamaModel $model) {
                Write-Good "Model already present: $model"
                continue
            }
            if (Ask-YesNo "Download missing model '$model' now?" $true) {
                & ollama pull $model
                if ($LASTEXITCODE -eq 0) { Write-Good "Downloaded $model" }
                else { Write-Warn "Could not download $model. Retry later with: ollama pull $model" }
            }
        }
    }

    Write-Step '9/10 Installing optional Sentinel and Aurora voice models'
    if ($SkipVoice) {
        Write-Warn 'Voice models skipped.'
    } elseif (Test-Path (Join-Path $VenvDir 'Lib\site-packages\piper')) {
        if (Ask-YesNo 'Download the DPN Sentinel and DPN Aurora neural voice files now?' $true) {
            & $VenvPython (Join-Path $Root 'manage.py') install-voices sentinel aurora
            if ($LASTEXITCODE -eq 0) { Write-Good 'Neural voice profiles are installed.' }
            else { Write-Warn 'Voice models did not finish downloading. Run install_voice_windows.bat later.' }
        }
    } else {
        Write-Warn 'Piper is unavailable, so neural voice downloads were skipped.'
    }

    Write-Step '10/10 Validating the application core'
    & $VenvPython -m compileall -q (Join-Path $Root 'app')
    if ($LASTEXITCODE -ne 0) { throw 'Python compilation validation failed.' }
    & $VenvPython -c "import fastapi,uvicorn,httpx,pydantic,dotenv,bs4,docx,openpyxl,pptx,reportlab,pypdf,psutil,cryptography; import app.main; print('DPN AI core import passed')"
    if ($LASTEXITCODE -ne 0) { throw 'The DPN AI core import test failed.' }

    $DoctorPath = Join-Path $LogDir "doctor_$Timestamp.json"
    & $VenvPython (Join-Path $Root 'manage.py') doctor | Set-Content -Path $DoctorPath -Encoding UTF8
    if ($LASTEXITCODE -ne 0) { Write-Warn 'The diagnostic report completed with warnings.' }

    $state = [ordered]@{
        version = (Get-Content (Join-Path $Root 'VERSION') -Raw).Trim()
        installed_at = (Get-Date).ToString('o')
        python_version = $script:PythonInfo.Version
        python_executable = $script:PythonInfo.Executable
        repair_mode = [bool]$Repair
        install_log = $LogPath
        doctor_report = $DoctorPath
    } | ConvertTo-Json
    $state | Set-Content -Path (Join-Path $Root 'data\install_state.json') -Encoding UTF8

    Write-Host "`n============================================================" -ForegroundColor Green
    Write-Host 'DPN AI v5.0.7 installation/repair completed successfully.' -ForegroundColor Green
    Write-Host 'Launch it with: run_dpn_ai.bat' -ForegroundColor Green
    Write-Host 'Control Center: http://127.0.0.1:8787' -ForegroundColor Green
    Write-Host "Install log: $LogPath" -ForegroundColor Green
    Write-Host '============================================================' -ForegroundColor Green
    $ExitCode = 0
} catch {
    Write-Host "`n============================================================" -ForegroundColor Red
    Write-Host 'DPN AI installation stopped.' -ForegroundColor Red
    Write-Host "Actual error: $($_.Exception.Message)" -ForegroundColor Red
    Write-Host "Detailed log: $LogPath" -ForegroundColor Yellow
    Write-Host 'Run repair_windows.bat after correcting the reported problem.' -ForegroundColor Yellow
    Write-Host '============================================================' -ForegroundColor Red
    $ExitCode = 1
} finally {
    if ($TranscriptStarted) {
        try { Stop-Transcript | Out-Null } catch { }
    }
}

if (-not $NonInteractive) {
    Write-Host ''
    Read-Host 'Press Enter to close this window'
}
exit $ExitCode