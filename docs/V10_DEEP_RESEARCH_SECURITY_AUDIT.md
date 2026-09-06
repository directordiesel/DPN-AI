# DPN AI v10.0.0 — Batch 7 Deep Research Security & Integration Audit

## Scope

This audit covers the Batch 7 Deep Research Engine from research planning through WEB, DOCUMENTS, and DATA evidence admission, claim extraction, deterministic assessment, citation validation, grounded writing, and mission-level release readiness.

## Trust boundaries verified

- WEB research reuses the existing bounded WebResearchRuntime rather than introducing a second unrestricted network client.
- DOCUMENTS research reuses scoped RAG retrieval and revalidates project/knowledge-base namespace before evidence admission.
- DATA research uses the governed read-only SQLite connector. It accepts explicit bounded DataQuerySpec objects only; it does not translate natural-language research objectives into SQL.
- Evidence graph admission requires stable source/evidence identities and provenance and stages worker batches before graph mutation.
- Claim extraction is untrusted. Claims may reference only evidence already admitted to the graph.
- Claim batches are preflighted before mutation and are passed through deterministic fact checking, conflict detection, citation validation, and synthesis readiness.
- Final writer output cannot create authoritative citations. Citation markers are reconstructed from trusted graph relationships and revalidated before report completion.
- Disputed, unsupported, stale, or conflict-bearing claims block final synthesis.
- Mission-level release readiness requires required-task completion, no optional-workstream failure, deterministic claim readiness, citation validation, and ready synthesis.
- Required-task completion is evaluated by exact planned task IDs, not only by workstream identity, so future multi-task plans cannot satisfy release readiness merely because another task in the same workstream completed.

## Failure behavior

The Batch 7 pipeline fails closed on missing required workers, malformed evidence/provenance, graph identity collisions, missing explicit structured-data query specifications, unknown DATA task mappings, unsupported claim references, unresolved conflicts, invalid citations, writer claim invention, and incomplete grounded synthesis.

Optional research-task failures remain visible and prevent release-ready status; they are not silently upgraded to success because another workstream produced usable evidence.

## Approval and mutation review

Batch 7 introduces no new destructive connector operation, arbitrary SQL execution surface, permission escalation, approval bypass, or autonomous mutation path. Structured DATA research remains read-only. Existing connector/network/provider approval boundaries are preserved.

## Verification checkpoint

The end-to-end mission head `caaa8e0c3c3ab2bbbc89337dee4f4b54fa21615a` passed CI, DPN Security Gate v2, and Runtime & Recovery Assurance. The final audit hardening that follows this checkpoint must pass the same exact-head gate set before Batch 7 is considered merge-ready.

## Residual risk / next gate

Batch 7 remains draft until the final audit-hardening head is green. Batch completion should then be recorded in the v10 build tracker and the pull request may move to merge-readiness review. No stable v10.0.0 release is implied; later v10 batches remain required.
