# DPN AI v10 — Batch 8 Memory Release Evidence Audit

This checkpoint converts executed test evidence into the strict eight-family memory benchmark gate. It does not infer readiness from file presence, implementation claims, or a generic CI success flag.

## Trusted evidence boundary

`app/memory_release_audit_v10.py` defines an immutable mapping from every required memory benchmark family to exact pytest node IDs. The audit caller must provide the identities of tests that a trusted runner or CI adapter reports as passed or failed. The module never scans the repository and assumes existing tests passed.

A required test that is missing from executed-test evidence fails closed. A required test reported failed blocks release even if it also appears in the passed set. Unrelated test failures do not fabricate a memory-specific failure, although the repository-wide CI gate must still pass separately before Batch 8 can be merge-ready.

## Required benchmark families

The manifest covers:

- memory scope isolation;
- provenance integrity;
- conflict preservation;
- supersession lineage;
- recovery detection;
- retention bounds;
- trusted promotion;
- tool authorization.

Each family is converted into a `MemoryBenchmarkObservation` and evaluated through the existing `BenchmarkLaboratory` and strict `evaluate_memory_readiness` wrapper. Batch 8 requires every family to pass with success rate 1.0 and quality score 1.0.

## Release rule

Batch 8 is not release-ready unless all of the following are true:

1. every manifest-required test has trusted executed-pass evidence;
2. no manifest-required test has trusted failure evidence;
3. the eight-family memory benchmark gate passes;
4. repository CI passes on the exact head;
5. DPN Security Gate v2 passes on the exact head;
6. Runtime & Recovery Assurance passes on the exact head;
7. Windows Desktop Package is either passed or an expected skip;
8. no unresolved high-risk approval or destructive-memory action remains.

This audit is intentionally non-destructive and does not merge the pull request or modify persisted runtime memory.