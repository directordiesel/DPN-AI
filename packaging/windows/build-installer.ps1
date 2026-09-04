[CmdletBinding()]
param(
    [string]$Python = "python",
    [string]$Iscc,
    [switch]$SkipTests
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
Set-Location $RepoRoot

function Invoke-Checked {
    param([Parameter(Mandatory=$true)][string]$FilePath, [Parameter(ValueFromRemainingArguments=$true)][string[]]$Arguments)
    & $FilePath @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "Command failed with exit code $LASTEXITCODE: $FilePath $($Arguments -join ' ')"
    }
}

function Resolve-Iscc {
    param([string]$Requested)
    if ($Requested) {
        if (-not (Test-Path $Requested)) { throw "Inno Setup compiler was not found at: $Requested" }
        return (Resolve-Path $Requested).Path
    }

    $command = Get-Command ISCC.exe -ErrorAction SilentlyContinue
    if ($command) { return $command.Source }

    $candidates = @(
        (Join-Path ${env:ProgramFiles(x86)} "Inno Setup 6\ISCC.exe"),
        (Join-Path $env:ProgramFiles "Inno Setup 6\ISCC.exe")
    ) | Where-Object { $_ -and (Test-Path $_) }

    if ($candidates.Count -eq 0) {
        throw "Inno Setup 6 compiler (ISCC.exe) is required. Refusing to download or install build tools implicitly on the trusted runner."
    }
    return (Resolve-Path $candidates[0]).Path
}

$VersionPath = Join-Path $RepoRoot "VERSION"
if (-not (Test-Path $VersionPath)) { throw "VERSION file is missing." }
$Version = (Get-Content $VersionPath -Raw).Trim()
if (-not $Version) { throw "VERSION is empty." }

$PackageDir = Join-Path $RepoRoot "dist\DPN-AI"
$PackageManifestPath = Join-Path $PackageDir "build-manifest.json"
$PackageExe = Join-Path $PackageDir "DPN-AI.exe"
if (-not (Test-Path $PackageManifestPath)) { throw "Package build manifest is missing. Run build.ps1 first." }
if (-not (Test-Path $PackageExe)) { throw "Packaged DPN-AI.exe is missing. Run build.ps1 first." }

$PackageManifest = Get-Content $PackageManifestPath -Raw | ConvertFrom-Json
if ($PackageManifest.version -ne $Version) {
    throw "Package version '$($PackageManifest.version)' does not match VERSION '$Version'."
}
if ($PackageManifest.signing -ne "unsigned-development-artifact") {
    throw "Unexpected package signing state '$($PackageManifest.signing)'. Release signing is handled by a later gated stage."
}
$ActualPackageHash = (Get-FileHash -Algorithm SHA256 $PackageExe).Hash.ToLowerInvariant()
if ($ActualPackageHash -ne $PackageManifest.sha256) {
    throw "Packaged executable SHA-256 does not match build-manifest.json."
}

if (-not $SkipTests) {
    Invoke-Checked $Python -m pytest -q tests/test_v8_windows_packaging.py tests/test_v8_windows_installer.py
}

$Compiler = Resolve-Iscc $Iscc
$InstallerDefinition = Join-Path $RepoRoot "packaging\windows\DPN-AI.iss"
$InstallerOutput = Join-Path $RepoRoot "dist\installer"
if (-not (Test-Path $InstallerDefinition)) { throw "Installer definition is missing." }
Remove-Item -Recurse -Force $InstallerOutput -ErrorAction SilentlyContinue
New-Item -ItemType Directory -Force -Path $InstallerOutput | Out-Null

Invoke-Checked $Compiler "/DAppVersion=$Version" "/DSourceDir=$PackageDir" "/DOutputDir=$InstallerOutput" $InstallerDefinition

$InstallerName = "DPN-AI-Setup-$Version.exe"
$InstallerExe = Join-Path $InstallerOutput $InstallerName
if (-not (Test-Path $InstallerExe)) {
    throw "Inno Setup completed without producing $InstallerName"
}

$InstallerHash = (Get-FileHash -Algorithm SHA256 $InstallerExe).Hash.ToLowerInvariant()
$InstallerManifest = [ordered]@{
    product = "DPN AI"
    publisher = "DPN Technology"
    version = $Version
    installer = $InstallerName
    sha256 = $InstallerHash
    source_executable_sha256 = $ActualPackageHash
    architecture = "x64-compatible"
    scope = "per-user-default"
    upgrade_behavior = "same-app-id-in-place-upgrade-repair"
    uninstall_data_policy = "preserve-user-data-outside-install-directory"
    built_utc = [DateTime]::UtcNow.ToString("o")
    signing = "unsigned-development-installer"
}
$InstallerManifestPath = Join-Path $InstallerOutput "installer-manifest.json"
$InstallerManifest | ConvertTo-Json -Depth 4 | Set-Content -Path $InstallerManifestPath -Encoding UTF8

Write-Host "DPN AI Windows installer created: $InstallerExe"
Write-Host "SHA-256: $InstallerHash"
Write-Host "Manifest: $InstallerManifestPath"
Write-Host "NOTE: installer is a development artifact and remains unsigned until the release signing stage."
