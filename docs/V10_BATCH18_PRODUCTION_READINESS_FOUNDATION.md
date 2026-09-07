# DPN AI v10.0.0 — Batch 18 Production Readiness + Stable Release

Batch 18 is the final production-readiness and stable-release phase of the single DPN AI v10.0.0 major-version program. It begins from the verified Batch 17 closure and intentionally separates release-readiness evidence from release execution.

## Production release authority

`app/production_release_v10.py` defines the stable-release evidence contract for exactly `10.0.0` / `v10.0.0`.

A candidate must bind one exact lowercase 40-character Git commit SHA and the exact governed validation set:

- repository CI;
- DPN Security Gate v2;
- Runtime & Recovery Assurance;
- Repository Health;
- Batch 8 memory readiness;
- Batch 9 artifact readiness;
- Batch 10 voice readiness;
- Batch 11 proactive readiness;
- Batch 12 specialist readiness;
- Batch 13 marketplace readiness;
- Batch 14 self-improvement readiness;
- Batch 15 full-system integration readiness;
- Batch 16 security regression readiness;
- Batch 17 performance readiness.

All gate values must be exact booleans and true. Missing, additional, false, or merely truthy values fail closed.

## Release artifact contract

A stable candidate must also prove the exact release artifact set expected by the existing release workflow:

- source archive;
- SHA-256 checksum file;
- release manifest;
- SPDX SBOM;
- tracked-source SHA-256 manifest;
- dependency inventory.

The evaluator rejects an already-published stable target so `v10.0.0` remains immutable rather than overwriteable.

## Evidence binding

Successful evaluation produces deterministic SHA-256 evidence bound to the exact target version, tag, commit SHA, validation-gate set, artifact contract, and unpublished-target state.

Whitespace normalization is not allowed for stable version or commit identity. Release identity must be byte-for-byte exact.

## Active version promotion

`app/version_promotion_v10.py` defines the governed active version surfaces. Historical v9 release documents and v9 regression fixtures are intentionally excluded and remain immutable historical evidence.

The governed active surfaces are repository `VERSION`, runtime `APP_VERSION`, README stable identity, service-worker cache identity, static index asset version token, static app service-worker version token, and ROADMAP current stable baseline.

`app/version_surface_audit_v10.py` reads those identities from a real repository tree instead of trusting caller-supplied claims. It rejects unreadable files, missing or ambiguous recognized identities, noncanonical `VERSION` formatting, stale versions, and surface-order drift. `require_promoted_repository_versions()` routes the collected values back through the same fail-closed promotion evaluator.

This keeps three states distinct: readiness infrastructure verified; metadata promoted; and release published. Promotion must not falsely treat publication as complete. During the metadata-promoted but unpublished state, README release wording says release candidate / publication pending rather than claiming that the v10 GitHub Release already exists.

## Non-authorizing boundary

A successful Batch 18 evaluation may report `ready_for_version_promotion=true` and `ready_for_release_dispatch=true`, but it always reports `execution_authorized=false` and `release_publish_authorized=false`.

The evaluator cannot edit `VERSION`, create a Git tag, merge a pull request, dispatch GitHub Actions, create or overwrite a GitHub Release, or bypass repository approval, ToolRegistry, or ApprovalSecurity controls.

Stable release publication remains an explicit external action through the existing release workflow after the repository itself is promoted to v10 and all final exact-head checks pass.

## Immutable Batch 18 CI contract

`app/production_release_gate_v10.py` defines nine mandatory release-readiness families:

1. `stable_version_identity`
2. `exact_commit_binding`
3. `validation_gate_integrity`
4. `strict_gate_boolean_integrity`
5. `release_artifact_contract`
6. `immutable_release_target`
7. `non_authorizing_release_evidence`
8. `deterministic_commit_bound_evidence`
9. `active_version_surface_coherence`

`app/production_release_ci_v10.py` executes only the exact pytest node IDs in that manifest. `.github/scripts/production_release_readiness_v10.py` is the repository-root-safe entrypoint, and the normal CI workflow runs the Batch 18 gate on Ubuntu/Python 3.11 after the Batch 17 performance gate.

The active-version family covers strict promotion-evidence semantics. Repository-backed collector tests independently verify extraction and ambiguity handling. The final promotion head additionally runs the repository-backed promoted-state audit against the real checkout before any publication eligibility is claimed.

## Version promotion status

The governed active metadata has now been promoted to `10.0.0`. The guarded promotion validated the real repository surfaces and the focused version/UI regression suite before committing the change. The temporary write-capable promotion workflow removed itself from the promoted commit.

This is still a release-candidate state, not a publication claim. The promoted exact head must pass the complete normal read-only CI, security, runtime/recovery, repository-health, and Batch 8–18 release-readiness chain before Batch 18 can be closed or the stable release can be prepared for explicit publication.
