# DPN AI v10.0.0 — Batch 17 Performance + Benchmark Optimization

Batch 17 begins the performance and benchmark optimization phase after the verified Batch 16 security/regression closure. This checkpoint adds a fail-closed optimization authority over the existing `BenchmarkLaboratory`; it does not create a second benchmark engine or a new execution authority.

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

## Evidence binding

Each evaluation receives a deterministic SHA-256 candidate digest bound to:

- candidate ID;
- benchmark model identity;
- the sorted mandatory family set;
- exact task IDs;
- baseline/candidate success and quality evidence;
- latency, retry, and token evidence;
- per-family pass/failure state.

JSON serialization rejects non-finite values through the underlying benchmark validation and `allow_nan=False` digest construction.

## Security boundary

Performance evidence is not authorization. Every evaluation reports `execution_authorized=false`. This checkpoint cannot change model routing, execute benchmarks, apply code, merge a pull request, deploy a release, mutate connectors, activate marketplace capabilities, or bypass ToolRegistry/ApprovalSecurity.

A faster candidate that loses correctness, quality, reliability, or resource efficiency fails closed. Batch 17 optimization therefore narrows candidates to measurable improvements without weakening the Batch 16 security contract.

## Regression coverage

`tests/test_performance_optimization_v10.py` covers:

- real latency improvement with preserved success/quality;
- benchmark task omission and duplicate-task rejection;
- success/quality trade-off rejection;
- retry regression rejection;
- token regression rejection;
- no-op candidate rejection;
- incomplete token evidence rejection;
- zero-baseline resource growth rejection;
- strict policy validation.

## Remaining Batch 17 work

This is the Batch 17 foundation, not release closure. Remaining work includes broader cross-capability performance families, persistent baseline/candidate evidence, deterministic resource-budget profiles, end-to-end benchmark optimization, an immutable Batch 17 release manifest, dedicated CI readiness gate, and exact-head completion evidence.
