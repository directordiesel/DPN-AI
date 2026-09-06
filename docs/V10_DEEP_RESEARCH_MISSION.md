# DPN AI v10.0.0 Deep Research Mission Orchestrator

## Purpose

`app/deep_research_mission_v10.py` is the bounded end-to-end orchestration layer for the v10 Deep Research Engine. It does not replace the individual WEB, DOCUMENTS, DATA, claim-validation, fact-checking, citation, or writing trust boundaries. It coordinates those already-governed components into one deterministic mission and exposes release-readiness evidence.

## Mission flow

1. `ResearchDirector` builds the active WEB / DOCUMENTS / DATA plan from the mission request.
2. Each enabled workstream executes sequentially against a shared `EvidenceGraph`.
3. Required task failure stops the mission immediately.
4. Optional task failure is retained as explicit bounded failure evidence and can never be silently promoted to release-ready status.
5. DATA tasks require a caller-supplied `DataQuerySpec`; the mission layer never turns natural language into SQL or invents a table/query.
6. Admitted evidence is passed to `DeepResearchClaimOrchestrator`.
7. Claims must survive provenance validation, deterministic fact checking, conflict detection, citation validation, and synthesis-readiness evaluation.
8. `DeepResearchWriter` runs only through its existing verified-claim boundary and rebuilds citations from trusted graph relationships.
9. Mission release readiness is true only if all required tasks completed, no optional workstream failed, claim readiness is true, citation validation is true, and final synthesis is ready.

## Fail-closed properties

The mission orchestrator deliberately does not grant approvals, execute destructive connector actions, broaden database permissions, open arbitrary files, or add a generic network primitive. It relies on the existing workers to enforce their transport-specific restrictions and adds orchestration-level checks around task identity, data-query mapping, required/optional failure semantics, and readiness aggregation.

A missing WEB worker fails the default required WEB task. Missing DOCUMENTS or DATA workers are explicit optional failures when those workstreams are enabled. Missing DATA query specifications are also explicit failures rather than an invitation to derive SQL from model output.

Unknown `data_queries` task IDs are rejected before any worker runs. This prevents a caller from smuggling structured-data work outside the active Research Director plan.

## Partial missions

A mission can still produce a grounded report from the evidence that was successfully admitted when an optional workstream fails. Such a result is reported as `partial`, never `ready`. The failure is included in `task_failures`, and `release_readiness.release_ready` remains false.

This distinction is intentional: a readable report is not equivalent to a complete research mission.

## Release-readiness contract

A mission is release-ready only when all of the following are true:

- every required Research Director task completed;
- no enabled optional workstream failed;
- deterministic claim readiness is true;
- citation validation is true;
- the evidence-grounded writer returned `ready`.

The result also records completed and failed workstreams, source/evidence/claim counts, optional failure count, claim assessment, citation acceptance, synthesis status, and the final grounded report.

## Regression coverage

`tests/test_deep_research_mission_v10.py` verifies:

- a WEB + DOCUMENTS + governed DATA mission reaches end-to-end release readiness;
- mixed-workstream evidence survives claim extraction through trusted citation rendering;
- an optional workstream failure remains explicit and prevents a false release-ready result;
- required WEB failure stops before claim extraction or writing;
- a missing explicit DATA query is not inferred from natural language and is recorded as a failure;
- DATA query mappings cannot target tasks outside the active mission plan.

## Remaining Batch 7 work

This checkpoint completes the first bounded mission-level integration path. Batch 7 still requires final security/integration audit evidence, build-tracker/release-readiness consolidation, exact-head CI verification, and any repairs revealed by those gates before the Deep Research batch is merge-ready.
