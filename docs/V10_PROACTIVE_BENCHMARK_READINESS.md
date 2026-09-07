# DPN AI v10.0.0 — Proactive Intelligence Benchmark & Release Readiness

## Mandatory benchmark families

Batch 11 release readiness requires exact evidence for five families:

1. `proactive_trusted_source_integrity` — trusted source evidence is host-registered, freshness-bound, and SHA-256 identified.
2. `proactive_lifecycle_recovery` — enabled persistent definitions survive reconstruction and do not replay before their next due time.
3. `proactive_duplicate_suppression` — repeated active edge conditions cannot repeatedly propose the same action.
4. `proactive_approval_boundary` — trusted proposals re-enter `ToolRegistry.execute()` and approval-pending dispatch is idempotent.
5. `proactive_mission_connector_sources` — mission and connector proactive inputs are derived from existing read models without causing mission or connector execution.

Every family requires a 1.0 success rate and 1.0 quality score in the v10 benchmark readiness evaluator.

## Exact release evidence

`app/proactive_release_audit_v10.py` maps each family to one immutable pytest node in `tests/test_proactive_release_cases_v10.py`. Aggregate test counts or caller-selected test identifiers cannot replace these cases.

The audit fails closed when:

- a mandatory node is missing;
- a mandatory node failed;
- a test is simultaneously claimed as passed and failed;
- any benchmark family fails the strict readiness thresholds.

## Executable CI gate

`app/proactive_release_ci_v10.py` runs exactly the immutable release manifest and only emits ready evidence after pytest returns success and the release audit passes.

`.github/scripts/proactive_release_readiness_v10.py` bootstraps the repository root before importing the harness, matching the hardened Batch 8–10 pattern.

GitHub Actions runs **Batch 11 proactive release readiness** only on Ubuntu/Python 3.11 after the full repository suite and previous v10 release gates. The other matrix lanes still run the full suite for portability/regression coverage.

## Security meaning

A successful Batch 11 release gate proves the proactive control plane preserves its non-execution boundary. It does not pre-authorize any future proactive action. Actual external/execute/destructive tool use still requires the live ToolRegistry risk/gate and ApprovalSecurity decision at dispatch time.
