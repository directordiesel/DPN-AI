# DPN AI v9.0.0 Release Candidate 1

Version: `9.0.0-rc.1`

This branch is the DPN AI v9 release-candidate integration point after completion of development Batches 1–17.

## Promotion requirements

The release candidate must remain fail closed until all of the following evidence is green for the exact candidate head:

- CI
- DPN Security Gate v2
- Runtime & Recovery Assurance
- applicable desktop/mobile packaging validation
- v9 production-readiness evaluation coverage
- release-engineering evidence for version coherence, manifest/checksums/SBOM, installer/package verification, and rollback readiness

## Release policy

- A release candidate is not a stable release.
- Do not publish or tag `v9.0.0` stable from a red or partially validated head.
- Do not substitute checks from an older commit for the exact candidate head.
- Any candidate code change invalidates previous exact-head evidence and requires validation again.
- Stable promotion must preserve security, approval, vault, recovery, and supply-chain controls.

## Major v9 capability areas

DPN AI v9 development includes the intelligence runtime, coding/repository engineering, permissions and sandbox governance, memory/RAG, research, artifact tooling, image/vision provider architecture, autonomous workflows, voice/multimodal sessions, desktop UX, Android v2 trust controls, model routing/failover, security/vault/audit hardening, recovery/resource/update policy, SDK/integration contracts, evaluation gates, and release engineering.

## Known provider boundary

Image generation has a real ComfyUI path. Image editing and vision remain provider-capability dependent and fail closed when an implementation is not configured. Release documentation must not represent unavailable providers as active.
