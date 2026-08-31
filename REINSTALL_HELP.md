> **Fix for your exact error:** v5.0.6 removes the multiline `python -c` check that PowerShell 5.1 corrupted at line 3.

# DPN AI v5.0.6 Reinstall and Repair Guide

## Clean reinstall after losing the old files

1. Download `DPN_AI_v5.0.6_INSTALLER_HOTFIX.zip`.
2. Right-click the ZIP and select **Extract All**.
3. Open the extracted `DPN_AI_v5.0.6_INSTALLER_HOTFIX` folder.
4. Double-click `repair_windows.bat`.
5. Keep the installer window open until it reports completion.
6. Start DPN AI using `run_dpn_ai.bat`.

Do not launch the installer from inside the ZIP preview. Windows may place only the batch file in a temporary folder, causing the rest of the release to appear missing.

## When the normal repair still fails

Run `install_core_only_windows.bat`. This installs the DPN AI application without downloading Ollama models or neural voices. After the control center works, install those components separately:

```text
ollama pull qwen3.5:9b
ollama pull nomic-embed-text
install_voice_windows.bat
```

## Where the real error is recorded

Every install attempt writes a full transcript to:

```text
install_logs\install_YYYYMMDD_HHMMSS.log
```

The final red error shown in the installer is also written there. The diagnostic JSON is saved beside it as `doctor_YYYYMMDD_HHMMSS.json` after a successful core installation.

## Common errors

### No compatible Python was found

Install a 64-bit Python 3.11 or newer release. The repaired installer accepts `py`, `python`, or `python3`; the original installer accepted only `py`.

### The release is incomplete

The ZIP was not fully extracted, or antivirus software removed a file. Extract the archive again into a normal writable folder such as:

```text
C:\DPN-AI
```

### The folder is not writable

Move DPN AI out of `Program Files`, a protected network folder, or a read-only location. A user-owned folder such as `C:\DPN-AI` is recommended.

### Required Python dependencies could not be installed

Check the newest install log for the package name. Confirm the computer has internet access and that antivirus or a corporate proxy is not blocking Python package downloads. The installer automatically retries without the pip cache.

### Ollama is missing or will not start

This no longer blocks installation. Finish the DPN AI core installation, install or open Ollama later, and then pull the models. Ollama for Windows requires Windows 10 or later.

### Voice packages or voice models failed

The AI core remains usable. Run `install_voice_windows.bat` after the application is working.

### Existing environment is damaged

Run `repair_windows.bat`. The installer moves a broken environment to a timestamped `.venv_broken_*` folder and creates a fresh one. It does not delete project data or the workspace.

## Preserved folders

Repair mode preserves these when they exist:

```text
.env
data\
workspace\
plugins\
skills\
```

Only an invalid `.venv` is replaced.