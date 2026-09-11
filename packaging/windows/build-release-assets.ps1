[CmdletBinding()]
param(
    [string]$Python = "python",
    [Parameter(Mandatory=$true)][string]$Version,
    [Parameter(Mandatory=$true)][ValidateSet("stable", "beta")][string]$Channel,
    [string]$TimestampUrl = "https://timestamp.digicert.com"
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
Set-Location $RepoRoot

function Assert-SecretEnvironment {
    $required = @(
        "DPN_WINDOWS_SIGNING_PFX_B64",
        "DPN_WINDOWS_SIGNING_PFX_PASSWORD",
        "DPN_UPDATE_ED25519_PRIVATE_KEY_B64",
        "DPN_UPDATE_ED25519_PUBLIC_KEY_HEX"
    )
    foreach ($name in $required) {
        $value = [Environment]::GetEnvironmentVariable($name)
        if ([string]::IsNullOrWhiteSpace($value)) {
            throw "Required production signing secret is not configured: $name"
        }
    }
}

function Invoke-Checked {
    param(
        [Parameter(Mandatory=$true)][string]$FilePath,
        [Parameter(ValueFromRemainingArguments=$true)][string[]]$Arguments
    )
    & $FilePath @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "Command failed with exit code $LASTEXITCODE"
    }
}

$RepositoryVersion = (Get-Content (Join-Path $RepoRoot "VERSION") -Raw).Trim()
if ($RepositoryVersion -ne $Version) {
    throw "Requested production version '$Version' does not match repository VERSION '$RepositoryVersion'."
}
if ($TimestampUrl -notmatch '^https://') {
    throw "Production timestamp URL must use HTTPS."
}

Assert-SecretEnvironment

$PfxPath = Join-Path $env:RUNNER_TEMP "dpn-production-signing.pfx"
$TrustRootPath = Join-Path $env:RUNNER_TEMP "update-trust.json"
$CertificateThumbprint = $null
$ImportedCertificates = @()
$PfxBytes = $null
$Password = $null

try {
    try {
        $PfxBytes = [Convert]::FromBase64String($env:DPN_WINDOWS_SIGNING_PFX_B64)
    }
    catch {
        throw "DPN_WINDOWS_SIGNING_PFX_B64 is not valid base64."
    }
    if ($PfxBytes.Length -le 0) {
        throw "DPN Windows signing PFX is empty."
    }
    [IO.File]::WriteAllBytes($PfxPath, $PfxBytes)

    $Password = ConvertTo-SecureString $env:DPN_WINDOWS_SIGNING_PFX_PASSWORD -AsPlainText -Force
    $Imported = Import-PfxCertificate -FilePath $PfxPath -CertStoreLocation "Cert:\CurrentUser\My" -Password $Password -Exportable:$false
    $ImportedCertificates = @($Imported)
    $Certificate = $ImportedCertificates | Where-Object { $_.HasPrivateKey } | Select-Object -First 1
    if (-not $Certificate) {
        throw "Imported PFX contains no certificate with a private key."
    }

    $CertificateThumbprint = (($Certificate.Thumbprint -replace '\s','')).ToUpperInvariant()
    if ($CertificateThumbprint -notmatch '^[A-F0-9]{40,64}$') {
        throw "Imported signing certificate returned an invalid thumbprint."
    }
    if ($env:GITHUB_ACTIONS -eq "true") {
        Write-Output "::add-mask::$CertificateThumbprint"
    }

    Invoke-Checked $Python ".github/scripts/write_update_trust_root.py" "--output" $TrustRootPath
    if (-not (Test-Path $TrustRootPath -PathType Leaf)) {
        throw "Production update trust root was not generated."
    }
    $env:DPN_UPDATE_TRUST_FILE = $TrustRootPath

    $BuildParameters = @{
        Python = $Python
        CertificateThumbprint = $CertificateThumbprint
        TimestampUrl = $TimestampUrl
        RequireSigned = $true
    }
    & (Join-Path $PSScriptRoot "build.ps1") @BuildParameters

    $InstallerParameters = @{
        Python = $Python
        CertificateThumbprint = $CertificateThumbprint
        TimestampUrl = $TimestampUrl
        RequireSigned = $true
    }
    & (Join-Path $PSScriptRoot "build-installer.ps1") @InstallerParameters

    $InstallerRoot = Join-Path $RepoRoot "dist\installer"
    $InstallerPath = Join-Path $InstallerRoot "DPN-AI-Setup-$Version.exe"
    $InstallerManifestPath = Join-Path $InstallerRoot "installer-manifest.json"
    $UpdateManifestPath = Join-Path $InstallerRoot "update-manifest.json"
    $SourceBuildManifest = Join-Path $RepoRoot "dist\DPN-AI\build-manifest.json"

    if (-not (Test-Path $InstallerPath -PathType Leaf)) {
        throw "Production installer was not created."
    }
    if (-not (Test-Path $SourceBuildManifest -PathType Leaf)) {
        throw "Production source build manifest was not created."
    }
    $SourceManifest = Get-Content $SourceBuildManifest -Raw | ConvertFrom-Json
    $TrustRootData = Get-Content $TrustRootPath -Raw | ConvertFrom-Json
    $ExpectedTrustHash = (Get-FileHash -Algorithm SHA256 $TrustRootPath).Hash.ToLowerInvariant()
    if (-not $SourceManifest.update_trust_configured) {
        throw "Production package manifest does not record an update trust root."
    }
    if ($SourceManifest.update_trust_root_sha256 -ne $ExpectedTrustHash) {
        throw "Production package trust-root hash does not match the generated trust root."
    }
    if ($SourceManifest.update_trust_public_key_sha256 -ne $TrustRootData.public_key_sha256) {
        throw "Production package trust root is not bound to the configured update verification key."
    }

    Invoke-Checked $Python ".github/scripts/sign_update_manifest.py" "--installer" $InstallerPath "--installer-manifest" $InstallerManifestPath "--version" $Version "--channel" $Channel "--output" $UpdateManifestPath

    $InstallerManifest = Get-Content $InstallerManifestPath -Raw | ConvertFrom-Json
    if ($InstallerManifest.signing -ne "signed-production-installer") {
        throw "Installer manifest does not record a signed production installer."
    }

    $InstallerSignature = Get-AuthenticodeSignature -FilePath $InstallerPath
    if ($InstallerSignature.Status -ne [System.Management.Automation.SignatureStatus]::Valid) {
        throw "Production installer Authenticode verification failed with status '$($InstallerSignature.Status)'."
    }
    if (-not $InstallerSignature.SignerCertificate) {
        throw "Production installer Authenticode verification returned no signer certificate."
    }
    $ActualThumbprint = (($InstallerSignature.SignerCertificate.Thumbprint -replace '\s','')).ToUpperInvariant()
    $ManifestThumbprint = (($InstallerManifest.signer_thumbprint -replace '\s','')).ToUpperInvariant()
    if ($ActualThumbprint -ne $ManifestThumbprint -or $ActualThumbprint -ne $CertificateThumbprint) {
        throw "Production installer signer identity verification failed."
    }

    Copy-Item $SourceBuildManifest (Join-Path $InstallerRoot "source-build-manifest.json") -Force

    $VerifyScript = @'
from pathlib import Path
import os

from desktop.updater import SignedUpdateManifest, verify_artifact, verify_manifest_signature

root = Path("dist/installer")
version = os.environ["DPN_RELEASE_VERSION"]
channel = os.environ["DPN_RELEASE_CHANNEL"]
installer = root / f"DPN-AI-Setup-{version}.exe"
manifest = SignedUpdateManifest.parse((root / "update-manifest.json").read_text(encoding="utf-8"))
public_hex = os.environ["DPN_UPDATE_ED25519_PUBLIC_KEY_HEX"].strip().lower()
if len(public_hex) != 64 or any(ch not in "0123456789abcdef" for ch in public_hex):
    raise SystemExit("Configured update public key is invalid")
if not verify_manifest_signature(manifest, bytes.fromhex(public_hex)):
    raise SystemExit("Update manifest Ed25519 verification failed")
verify_artifact(installer, manifest.artifact)
if manifest.artifact.version != version:
    raise SystemExit("Update manifest version mismatch")
if manifest.artifact.channel != channel:
    raise SystemExit("Update manifest channel mismatch")
print("Production update manifest verification PASS")
'@
    $env:DPN_RELEASE_VERSION = $Version
    $env:DPN_RELEASE_CHANNEL = $Channel
    $VerifyScript | & $Python -
    if ($LASTEXITCODE -ne 0) {
        throw "Production update verification failed."
    }

    $ChecksumScript = @'
import hashlib
from pathlib import Path

root = Path("dist/installer")
files = sorted(
    [
        *root.glob("DPN-AI-Setup-*.exe"),
        root / "installer-manifest.json",
        root / "source-build-manifest.json",
        root / "update-manifest.json",
    ],
    key=lambda path: path.name,
)
if len([path for path in files if path.suffix.lower() == ".exe"]) != 1:
    raise SystemExit("Expected exactly one production installer executable")
if any(not path.is_file() for path in files):
    raise SystemExit("One or more production release files are missing")
lines = []
for path in files:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    lines.append(f"{digest.hexdigest()}  {path.name}")
(root / "WINDOWS_SHA256SUMS.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
'@
    $ChecksumScript | & $Python -
    if ($LASTEXITCODE -ne 0) {
        throw "Windows checksum generation failed."
    }

    Write-Host "Production Windows release assets verified."
    Write-Host "Installer: $InstallerPath"
    Write-Host "Update channel: $Channel"
}
finally {
    Remove-Item -LiteralPath $PfxPath -Force -ErrorAction SilentlyContinue
    Remove-Item -LiteralPath $TrustRootPath -Force -ErrorAction SilentlyContinue
    if ($PfxBytes) {
        [Array]::Clear($PfxBytes, 0, $PfxBytes.Length)
    }
    foreach ($ImportedCertificate in $ImportedCertificates) {
        if ($ImportedCertificate -and $ImportedCertificate.Thumbprint) {
            $ImportedThumbprint = (($ImportedCertificate.Thumbprint -replace '\s','')).ToUpperInvariant()
            $ImportedPath = "Cert:\CurrentUser\My\$ImportedThumbprint"
            if (Test-Path $ImportedPath) {
                Remove-Item -LiteralPath $ImportedPath -Force -ErrorAction SilentlyContinue
            }
        }
    }
    if ($Password) {
        $Password.Dispose()
    }
    Remove-Item Env:DPN_RELEASE_VERSION -ErrorAction SilentlyContinue
    Remove-Item Env:DPN_RELEASE_CHANNEL -ErrorAction SilentlyContinue
    Remove-Item Env:DPN_UPDATE_TRUST_FILE -ErrorAction SilentlyContinue
}
