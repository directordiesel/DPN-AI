[CmdletBinding()]
param(
    [string]$Python = "python",
    [switch]$SkipInstall,
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

if (-not (Test-Path (Join-Path $RepoRoot "VERSION"))) {
    throw "VERSION file is missing. Refusing to create an unversioned package."
}

if ($RequireSigned -and -not $CertificateThumbprint) {
    throw "Production signing is required but no CertificateThumbprint was supplied."
}

if (-not $SkipInstall) {
    Invoke-Checked $Python -m pip install --disable-pip-version-check -r requirements-build.txt
}

if (-not $SkipTests) {
    Invoke-Checked $Python -m pytest -q tests/test_v8_desktop_platform.py tests/test_v8_desktop_supervisor.py tests/test_v8_desktop_control_center.py tests/test_v8_desktop_service_api.py tests/test_v8_windows_packaging.py
}

$DistRoot = Join-Path $RepoRoot "dist"
$BuildRoot = Join-Path $RepoRoot "build"
Remove-Item -Recurse -Force (Join-Path $DistRoot "DPN-AI") -ErrorAction SilentlyContinue
Remove-Item -Recurse -Force (Join-Path $BuildRoot "DPN-AI") -ErrorAction SilentlyContinue

Invoke-Checked $Python -m PyInstaller --noconfirm --clean --distpath $DistRoot --workpath $BuildRoot (Join-Path $RepoRoot "packaging\windows\DPN-AI.spec")

$Exe = Join-Path $DistRoot "DPN-AI\DPN-AI.exe"
if (-not (Test-Path $Exe)) {
    throw "PyInstaller completed without producing DPN-AI.exe"
}

$SigningState = "unsigned-development-artifact"
$SignerThumbprint = $null
$SignerSubject = $null
if ($CertificateThumbprint) {
    $signScript = Join-Path $PSScriptRoot "sign.ps1"
    $signingJson = & $signScript -FilePath $Exe -CertificateThumbprint $CertificateThumbprint -TimestampUrl $TimestampUrl
    if ($LASTEXITCODE -ne 0) { throw "Production signing helper failed." }
    $signing = $signingJson | ConvertFrom-Json
    if ($signing.status -ne "signed-production-artifact") {
        throw "Unexpected signing helper state '$($signing.status)'."
    }
    $SigningState = "signed-production-artifact"
    $SignerThumbprint = $signing.thumbprint
    $SignerSubject = $signing.subject
}
if ($RequireSigned -and $SigningState -ne "signed-production-artifact") {
    throw "Production signing was required but DPN-AI.exe is not verified as signed."
}

$Version = (Get-Content (Join-Path $RepoRoot "VERSION") -Raw).Trim()
$Hash = (Get-FileHash -Algorithm SHA256 $Exe).Hash.ToLowerInvariant()
$Manifest = [ordered]@{
    product = "DPN AI"
    version = $Version
    executable = "DPN-AI.exe"
    sha256 = $Hash
    architecture = $env:PROCESSOR_ARCHITECTURE
    built_utc = [DateTime]::UtcNow.ToString("o")
    signing = $SigningState
    signer_thumbprint = $SignerThumbprint
    signer_subject = $SignerSubject
}
$ManifestPath = Join-Path $DistRoot "DPN-AI\build-manifest.json"
$Manifest | ConvertTo-Json -Depth 4 | Set-Content -Path $ManifestPath -Encoding UTF8

Write-Host "DPN AI Windows package created: $Exe"
Write-Host "SHA-256: $Hash"
Write-Host "Signing: $SigningState"
Write-Host "Manifest: $ManifestPath"
if ($SigningState -eq "unsigned-development-artifact") {
    Write-Host "NOTE: development artifact remains unsigned. Use -RequireSigned with a trusted certificate for release builds."
}
