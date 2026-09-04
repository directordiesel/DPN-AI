[CmdletBinding()]
param(
    [string]$Python = "python",
    [string]$Iscc,
    [switch]$SkipTests,
    [string]$CertificateThumbprint,
    [string]$TimestampUrl = "http://timestamp.digicert.com",
    [switch]$RequireSigned
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
Set-Location $RepoRoot

function Invoke-Checked {
    param([Parameter(Mandatory=$true)][string]$FilePath, [Parameter(ValueFromRemainingArguments=$true)][string[]]$Arguments)
    & $FilePath @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "Command failed with exit code ${LASTEXITCODE}: $FilePath $($Arguments -join ' ')"
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

if ($RequireSigned -and -not $CertificateThumbprint) {
    throw "Production signing is required but no CertificateThumbprint was supplied."
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
if ($PackageManifest.signing -notin @("unsigned-development-artifact", "signed-production-artifact")) {
    throw "Unexpected package signing state '$($PackageManifest.signing)'."
}
if ($RequireSigned -and $PackageManifest.signing -ne "signed-production-artifact") {
    throw "Production installer build requires the packaged executable to be signed first."
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

$SigningState = "unsigned-development-installer"
$SignerThumbprint = $null
$SignerSubject = $null
if ($CertificateThumbprint) {
    $signScript = Join-Path $PSScriptRoot "sign.ps1"
    $signingJson = & $signScript -FilePath $InstallerExe -CertificateThumbprint $CertificateThumbprint -TimestampUrl $TimestampUrl
    if ($LASTEXITCODE -ne 0) { throw "Installer signing helper failed." }
    $signing = $signingJson | ConvertFrom-Json
    if ($signing.status -ne "signed-production-artifact") {
        throw "Unexpected installer signing helper state '$($signing.status)'."
    }
    $SigningState = "signed-production-installer"
    $SignerThumbprint = $signing.thumbprint
    $SignerSubject = $signing.subject
}
if ($RequireSigned -and $SigningState -ne "signed-production-installer") {
    throw "Production signing was required but the installer is not verified as signed."
}

$InstallerHash = (Get-FileHash -Algorithm SHA256 $InstallerExe).Hash.ToLowerInvariant()
$InstallerManifest = [ordered]@{
    product = "DPN AI"
    publisher = "DPN Technology"
    version = $Version
    installer = $InstallerName
    sha256 = $InstallerHash
    source_executable_sha256 = $ActualPackageHash
    source_executable_signing = $PackageManifest.signing
    architecture = "x64-compatible"
    scope = "per-user-default"
    upgrade_behavior = "same-app-id-in-place-upgrade-repair"
    uninstall_data_policy = "preserve-user-data-outside-install-directory"
    built_utc = [DateTime]::UtcNow.ToString("o")
    signing = $SigningState
    signer_thumbprint = $SignerThumbprint
    signer_subject = $SignerSubject
}
$InstallerManifestPath = Join-Path $InstallerOutput "installer-manifest.json"
$InstallerManifest | ConvertTo-Json -Depth 4 | Set-Content -Path $InstallerManifestPath -Encoding UTF8

Write-Host "DPN AI Windows installer created: $InstallerExe"
Write-Host "SHA-256: $InstallerHash"
Write-Host "Signing: $SigningState"
Write-Host "Manifest: $InstallerManifestPath"
if ($SigningState -eq "unsigned-development-installer") {
    Write-Host "NOTE: development installer remains unsigned. Use -RequireSigned with a trusted certificate for release builds."
}
