# DPN AI v10 — Batch 8 Memory Release Evidence Audit

This checkpoint converts executed test evidence into the strict eight-family memory benchmark gate. It does not infer readiness from file presence, implementation claims, or a generic CI success flag.

## Trusted evidence boundary

`app/memory_release_audit_v10.py` defines an immutable mapping from every required memory benchmark family to exact pytest node IDs. The audit caller must provide the identities of tests that a trusted runner or CI adapter reports as passed or failed. The module never scans the repository and assumes existing tests passed.

A required test that is missing from executed-test evidence fails closed. A required test reported failed blocks release even if it also appears in the passed set. Unrelated test failures do not fabricate a memory-specific failure, although the repository-wide CI gate must still pass separately before Batch 8 can be merge-ready.

## Executable CI evidence

`app/memory_release_ci_v10.py` and `.github/scripts/memory_release_readiness_v10.py` close the gap between the immutable manifest and GitHub Actions. The harness obtains the required node IDs only from `required_memory_release_test_ids()`, executes exactly those tests through pytest, and accepts exit code zero as the trusted indication that every selected manifest test passed.

The caller cannot substitute arbitrary test IDs or self-assert successful cases. If pytest returns non-zero, the harness raises `MemoryReleaseCIError` and emits no ready evidence. If pytest succeeds, the exact selected IDs are supplied to `audit_memory_release_evidence`; the harness then requires the strict benchmark result to be ready before it emits a machine-readable JSON payload.

The main CI workflow executes this dedicated gate on the Ubuntu / Python 3.11 lane after the complete repository test suite. The normal cross-platform CI suite continues to run on Ubuntu and Windows for Python 3.11 and 3.12.

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
