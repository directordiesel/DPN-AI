# DPN AI v9.0.0 Stable Release

Version: `9.0.0`

DPN AI v9.0.0 is the stable promotion of the fully validated v9 release-candidate code line after completion of all 18 development batches.

## Stable promotion requirements

The stable release must be promoted only from an exact head where the required repository gates are green:

- CI
- DPN Security Gate v2
- Runtime & Recovery Assurance
- applicable desktop/mobile packaging validation
- v9 production-readiness evaluation coverage
- release-engineering checks for version coherence, release artifacts, integrity evidence, and rollback readiness

## Release artifact policy

The repository `Release` workflow publishes `v9.0.0` from `main` only after `VERSION` equals `9.0.0`. The release workflow generates and attaches:

- source ZIP archive
- SHA-256 release checksum
- release manifest containing repository, version, exact commit, workflow run, and generation time
- SPDX SBOM
- tracked-source SHA-256 manifest
- declared dependency inventory

Stable publication is not a prerelease and must not overwrite an existing tag.

## Capability boundary

DPN AI v9 includes the completed v9 intelligence, coding, permissions/sandbox, memory/RAG, research, artifact, workflow, voice/multimodal, desktop, Android, model-routing, security, recovery/update, SDK/integration, evaluation, and release-engineering work.

ComfyUI image generation is implemented. Image editing and vision remain provider-capability dependent and fail closed when an implementation is not configured; stable documentation must not represent an unavailable provider as active.
