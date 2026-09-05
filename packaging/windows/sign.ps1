[CmdletBinding()]
param(
    [Parameter(Mandatory=$true)][string]$FilePath,
    [Parameter(Mandatory=$true)][string]$CertificateThumbprint,
    [string]$TimestampUrl = "http://timestamp.digicert.com"
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

function Resolve-SignTool {
    $command = Get-Command signtool.exe -ErrorAction SilentlyContinue
    if ($command) { return $command.Source }

    $kitsRoot = Join-Path ${env:ProgramFiles(x86)} "Windows Kits\10\bin"
    if (Test-Path $kitsRoot) {
        $candidate = Get-ChildItem -Path $kitsRoot -Filter signtool.exe -Recurse -File -ErrorAction SilentlyContinue |
            Where-Object { $_.FullName -match '\\x64\\signtool\.exe$' } |
            Sort-Object FullName -Descending |
            Select-Object -First 1
        if ($candidate) { return $candidate.FullName }
    }

    throw "signtool.exe is required for production signing. Install the Windows SDK on the trusted runner."
}

if (-not (Test-Path $FilePath -PathType Leaf)) {
    throw "Signing target does not exist: $FilePath"
}

$thumbprint = ($CertificateThumbprint -replace '\s','').ToUpperInvariant()
if ($thumbprint -notmatch '^[A-F0-9]{40,64}$') {
    throw "Certificate thumbprint must be a 40-64 character hexadecimal value."
}
if (-not $TimestampUrl.StartsWith("https://") -and -not $TimestampUrl.StartsWith("http://")) {
    throw "TimestampUrl must be an HTTP(S) URL."
}

$signTool = Resolve-SignTool
& $signTool sign /sha1 $thumbprint /fd SHA256 /tr $TimestampUrl /td SHA256 $FilePath
if ($LASTEXITCODE -ne 0) {
    throw "signtool.exe failed with exit code $LASTEXITCODE"
}

$signature = Get-AuthenticodeSignature -FilePath $FilePath
if ($signature.Status -ne [System.Management.Automation.SignatureStatus]::Valid) {
    throw "Authenticode verification failed with status '$($signature.Status)'."
}
if (-not $signature.SignerCertificate) {
    throw "Authenticode verification returned no signer certificate."
}
$actualThumbprint = ($signature.SignerCertificate.Thumbprint -replace '\s','').ToUpperInvariant()
if ($actualThumbprint -ne $thumbprint) {
    throw "Signed file certificate thumbprint does not match the requested certificate."
}

[ordered]@{
    status = "signed-production-artifact"
    thumbprint = $actualThumbprint
    subject = $signature.SignerCertificate.Subject
    timestamp_url = $TimestampUrl
} | ConvertTo-Json -Compress
