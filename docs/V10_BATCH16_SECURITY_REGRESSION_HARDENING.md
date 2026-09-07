# DPN AI v10.0.0 — Batch 16 Security + Regression Hardening

Batch 16 hardens existing v10 authorities rather than adding a parallel execution architecture. The goal is to convert ambiguous, malformed, or incomplete evidence into explicit fail-closed outcomes before final production-readiness work.

## Checkpoint 1 — Benchmark evidence integrity

The benchmark laboratory now requires:

- `BenchmarkRun.passed` to be an actual boolean rather than a truthy caller-controlled value;
- caller-supplied timestamps to be timezone-aware ISO-8601 values normalized to UTC;
- regression thresholds to be strictly greater than zero so unchanged results cannot be classified as regressions at threshold zero.

These rules protect benchmark-gated routing, release evidence, and the approval-controlled self-improvement loop from malformed benchmark inputs.

## Checkpoint 2 — Repository path containment

The autonomous coding repository-intelligence layer now uses one strict repository-path normalizer for repository maps, change-impact requests, containment checks, diff-risk input, and security-finding paths.

Rejected evidence includes:

- POSIX absolute paths such as `/etc/passwd`;
- Windows drive-absolute and drive-relative paths such as `C:/...` and `C:...`;
- parent traversal (`..`);
- ambiguous dot segments (`.`);
- NUL-containing paths;
- empty/non-string path evidence.

The previous behavior could strip a leading slash and make an absolute path look repository-relative. Batch 16 removes that ambiguity. Invalid path evidence raises `CodingRepositoryError`; it is never normalized into an apparently valid repository member.

The special synthetic risk-finding path `*` remains allowed only for internally generated aggregate findings such as large-diff churn. Concrete security-finding paths must satisfy repository containment.

## Checkpoint 3 — CI conclusion integrity

`CIJobEvidence.passed` now means exactly one thing: the required CI job concluded with `success`.

The following no longer count as successful execution evidence:

- `skipped`;
- `neutral`;
- cancelled or timed-out jobs;
- failed jobs;
- unrecognized caller-supplied conclusion values.

Skipped/neutral jobs may still be useful diagnostic information, but they cannot prove that a required validation actually ran. When supplied to the coding orchestrator they produce a fail-closed CI analysis and cannot mark a pull request ready.

## Security boundary

These changes do not grant new tool, repository, provider, connector, deployment, or approval capabilities. They only narrow what evidence can be accepted as valid.

No direct `ToolRegistry._invoke()` path is introduced. No model-controlled approval flag is introduced. High/critical diff repair continues to require the existing approval policy. Full-system readiness remains evidence-only and non-executing.

## Regression coverage

The Batch 16 checkpoint expands:

- `tests/test_benchmark_laboratory_v10.py`;
- `tests/test_coding_repository_intelligence_v10.py`;
- `tests/test_coding_ci_orchestrator_v10.py`.

Mandatory negative paths include malformed boolean/timestamp benchmark evidence, zero regression thresholds, absolute/traversal repository paths, out-of-repository security findings, skipped/neutral CI results, and unrecognized CI conclusion types.

## Remaining Batch 16 work

After exact-head CI/security/recovery verification, continue hardening:

1. provider/model provenance and identity drift;
2. connector permission/risk drift;
3. approval-boundary tampering and stale approval evidence;
4. recovery/checkpoint integrity under malformed or replayed state;
5. cross-system adversarial negative-path release cases;
6. dedicated Batch 16 immutable hardening/readiness gate and completion evidence.
