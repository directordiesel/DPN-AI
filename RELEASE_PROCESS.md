# DPN Technology Release Process

This document defines the production release discipline for **DPN AI**. Production publication is performed only through the manual GitHub Actions **Release** workflow on main.

## Required GitHub signing material

Production releases fail closed unless all four values are configured outside the repository as GitHub Secrets:

- DPN_WINDOWS_SIGNING_PFX_B64 — base64-encoded Windows code-signing PFX
- DPN_WINDOWS_SIGNING_PFX_PASSWORD — password for that PFX
- DPN_UPDATE_ED25519_PRIVATE_KEY_B64 — base64-encoded raw 32-byte Ed25519 private seed
- DPN_UPDATE_ED25519_PUBLIC_KEY_HEX — the matching 32-byte public key as 64 hexadecimal characters

Private signing material must never be committed, attached to a release, written to repository files, or copied into runtime logs.

The Windows release helper imports the code-signing certificate as non-exportable, removes the temporary PFX, clears the decoded PFX bytes, removes all certificates imported from the PFX, and disposes the secure password object before the job exits.

## Prepare

1. Merge approved changes into main.
2. Update VERSION and all application-visible version locations.
3. Update README.md, CHANGELOG.md, and affected architecture, security, recovery, or migration documentation.
4. Confirm no live credentials, databases, vault keys, runtime state, private workspace files, or private exports are tracked.
5. Confirm the requested release tag is exactly v<VERSION>.
6. Do not manually create the production tag before dispatching the workflow.

## Production release workflow

Dispatch .github/workflows/release.yml manually from main with:

- version — exact tag matching repository VERSION, including the leading v
- prerelease — must agree with whether VERSION contains a SemVer prerelease suffix

The workflow executes these boundaries in order.

### 1. Security preflight

Before any production signing operation:

- validates the requested tag and prerelease state
- refuses an existing tag
- runs the portable repository/version guard
- runs tools/dpn_security_gate.py --github
- installs the pinned security-audit toolchain
- runs pip-audit across runtime, build, browser, desktop, and voice dependency declarations

Any preflight failure prevents signing.

### 2. Windows production assets

Only after security preflight passes, the Windows job:

- validates the release request again on Windows
- imports the PFX only for the duration of the job
- builds the packaged DPN AI executable
- Authenticode-signs and verifies the packaged executable
- builds the Windows installer
- Authenticode-signs and verifies the installer
- requires HTTPS timestamping
- creates an Ed25519-signed update manifest
- verifies the update signature using the separately configured public key
- verifies installer filename, size, SHA-256, version, and release channel
- creates WINDOWS_SHA256SUMS.txt
- creates GitHub/Sigstore SLSA build-provenance attestations for the signed installer and its production manifests
- uploads only the verified production bundle as a one-day workflow artifact

### 3. Independent publication verification

The Ubuntu publication job downloads the Windows bundle and independently verifies:

- every transferred file against WINDOWS_SHA256SUMS.txt
- production installer version and filename
- installer SHA-256
- production signing state and signer identity metadata
- source executable production signing state
- source/installer signer identity agreement
- Ed25519 update-manifest signature
- update artifact integrity
- version and stable/beta channel agreement

Publication does not continue if any transferred artifact or manifest is inconsistent.

### 4. GitHub Release

After the full release test suite and supply-chain generation pass, the workflow creates a separate GitHub/Sigstore build-provenance attestation for the source archive, then creates the GitHub Release and tag from the exact main commit.

Current release assets include:

- source ZIP
- source ZIP SHA-256
- release manifest
- SPDX SBOM
- tracked-source SHA-256 manifest
- declared dependency inventory
- Authenticode-signed Windows installer
- installer manifest
- source build manifest
- Ed25519-signed update manifest
- Windows release SHA-256 manifest

GitHub artifact attestations are stored by GitHub and bind the workflow-produced artifacts to their repository, commit, workflow identity, and Sigstore-backed provenance record. They complement rather than replace Authenticode, Ed25519, and SHA-256 verification.

Existing tags/releases are immutable. Publish a new version for every correction.

## Validation requirements

A production release is blocked unless the applicable checks pass, including:

- Main CI
- full pytest suite
- Python source compilation
- Repository Health
- DPN Security Gate
- advanced CodeQL
- Runtime & Recovery Assurance
- Windows validation
- release security preflight
- signed Windows artifact verification
- release bundle transfer verification

## Hotfixes

Reproduce the defect, add regression coverage where possible, make the smallest safe correction, pass the normal validation stack, increment VERSION, update release notes, and publish a new release. Never silently replace a previously published artifact.

## Repository governance

The release workflow re-runs critical validation internally because repository administration is a separate control. Branch protection or rulesets for main should require the repository security and CI checks and restrict direct pushes. Enabling those GitHub administrative controls does not replace the release workflow's own fail-closed checks.
