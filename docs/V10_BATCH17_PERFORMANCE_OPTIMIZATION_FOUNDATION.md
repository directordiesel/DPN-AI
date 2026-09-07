# DPN AI v10.0.0 — Batch 17 Performance + Benchmark Optimization

Batch 17 is the performance and benchmark optimization phase after the verified Batch 16 security/regression closure. It adds a fail-closed optimization authority over the existing `BenchmarkLaboratory`; it does not create a second benchmark engine or a new execution authority.

## Performance optimization authority

`app/performance_optimization_v10.py` compares explicit baseline and candidate `BenchmarkRun` evidence for one model identity and a host-supplied mandatory family set.

An optimization candidate must preserve the exact benchmark task IDs for every required family. Missing, added, or duplicate task IDs fail closed. This prevents a candidate from appearing faster by omitting difficult benchmark cases or substituting a smaller workload.

The default policy requires:

- candidate success rate of 1.0;
- candidate quality score of 1.0;
- zero success regression;
- zero quality regression;
- zero median-latency regression;
- zero retry regression;
- zero token-usage regression when complete token evidence is available;
- at least one measurable improvement in median latency, retries, or token usage across the required families.

Token evidence must be complete for every task in a family or absent for every task. Baseline/candidate token-evidence availability must match. Zero-valued resource baselines are handled without non-finite ratios and any growth from a zero baseline fails closed under the default policy.

## Durable evidence

`app/performance_evidence_v10.py` persists append-only optimization receipts bound to each evaluation by SHA-256. Identical replay is idempotent. Corrupt JSON, malformed schema, conflicting duplicate evidence, or any receipt claiming `execution_authorized=true` fails closed.

## Governed performance profiles

`app/performance_profiles_v10.py` defines host-owned profiles rather than allowing a candidate to select arbitrary benchmark families:

- `balanced_platform`
- `interactive_latency`
- `agent_efficiency`

Each profile binds a mandatory family set and explicit resource-regression policy. Unknown or malformed profile identities fail closed.

## Cross-profile acceptance

`app/performance_acceptance_v10.py` provides the Batch 17 cross-capability acceptance authority. A platform candidate is accepted only when all governed profiles are present, each profile evaluation passed, every evaluation is non-authorizing, each evaluation exactly matches the host-owned profile family set, and every profile binds to the same candidate ID and model identity.

This prevents mixing results from different builds or models into one apparent optimized release.

## Release contract

`app/performance_release_v10.py` defines an immutable eight-family release manifest. `app/performance_release_ci_v10.py` executes only those exact pytest node IDs, and `.github/scripts/performance_release_readiness_v10.py` is the repository-root-safe CI entrypoint. GitHub Actions runs the Batch 17 release gate on Ubuntu/Python 3.11 after the Batch 8–16 release gates.

## Security boundary

Performance evidence is not authorization. Every evaluation, durable receipt, release audit, and cross-profile acceptance result reports `execution_authorized=false`. Batch 17 cannot change model routing, execute benchmarks, apply code, merge a pull request, deploy a release, mutate connectors, activate marketplace capabilities, or bypass ToolRegistry/ApprovalSecurity.

A faster candidate that loses correctness, quality, reliability, identity integrity, benchmark coverage, or resource efficiency fails closed.
