# DPN AI v10.0.0 — Batch 17 Performance Release Readiness

Batch 17 adds an executable, fail-closed release gate for performance and benchmark optimization. Performance evidence is treated as release evidence only; it never grants execution, deployment, routing, merge, connector, marketplace, or approval authority.

## Mandatory release families

The immutable manifest in `app/performance_release_v10.py` binds Batch 17 readiness to seven exact pytest node IDs:

1. **measurable improvement integrity** — a candidate must demonstrate a real latency/resource improvement while preserving correctness and quality;
2. **benchmark task-set integrity** — baseline and candidate benchmark task IDs must match exactly, preventing omission-based benchmark gaming;
3. **quality/success preservation** — a faster candidate cannot trade away benchmark quality;
4. **resource regression integrity** — an apparent latency win cannot hide token/resource regression;
5. **durable evidence integrity** — conflicting durable evidence under one candidate digest fails closed;
6. **non-authorizing evidence** — any performance receipt claiming execution authorization is rejected;
7. **governed profile integrity** — host-owned performance profiles must remain valid and require measurable improvement.

## Executable release gate

`app/performance_release_ci_v10.py` executes only the manifest's exact pytest node IDs and blocks readiness if any required test fails. `.github/scripts/performance_release_readiness_v10.py` provides the repository-root-safe CI entrypoint.

GitHub Actions runs the Batch 17 gate on Ubuntu/Python 3.11 after the existing Batch 8–16 release gates. The normal full test suite still runs across Ubuntu and Windows on Python 3.11 and 3.12.

The audit rejects missing, failed, or unexpected evidence families. A successful result must report:

- `checkpoint=v10.0.0-batch-17`;
- `ready=true`;
- all seven required families present and true;
- no unexpected families;
- `execution_authorized=false`.

## Security boundary

Performance optimization is not permission escalation. Benchmark or resource improvements cannot change model routing, apply code, merge a pull request, deploy software, invoke tools, mutate connectors, activate marketplace capabilities, or approve destructive actions. Those actions remain governed by their existing authorities and approval boundaries.

Exact task parity, durable SHA-256-bound receipts, strict performance-profile identity, preserved correctness/quality, and bounded resource regressions remain required. Malformed, incomplete, ambiguous, conflicting, or authorizing performance evidence fails closed.

## Completion rule

Batch 17 is not complete merely because the release-gate files exist. Completion requires the exact final branch head to pass the full repository CI lane, DPN Security Gate v2, Runtime & Recovery Assurance, Repository Health, and the dedicated Batch 17 performance release-readiness gate. Completion evidence is recorded only after that exact-head verification succeeds.
