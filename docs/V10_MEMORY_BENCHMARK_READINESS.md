# DPN AI v10 Memory Benchmark Readiness

Batch 8 memory release readiness is measured through the existing v10 `BenchmarkLaboratory` and `evaluate_readiness` contracts. Memory does not use a separate, easier scorecard.

## Mandatory benchmark families

The memory runtime must provide evidence for all of the following families:

1. `memory_scope_isolation` — organization/user/project/conversation boundaries do not leak.
2. `memory_provenance_integrity` — typed provenance and evidence requirements are preserved and untrusted provenance cannot become trusted fact.
3. `memory_conflict_preservation` — conflicting versions remain visible/auditable rather than silently overwritten.
4. `memory_supersession_lineage` — replacements are evidence-backed, authority-bounded, non-destructive, and linked by a durable receipt.
5. `memory_recovery_detection` — malformed, dangling, cross-lineage, or cyclic history is surfaced as recovery-required.
6. `memory_retention_bounds` — working-memory bounds, TTL expiry, and persistent retention controls behave deterministically.
7. `memory_trusted_promotion` — only trusted Deep Research and integrity-verified mission evidence reaches the permitted durable layers.
8. `memory_tool_authorization` — agent-facing non-global access requires host authorization and consequential supersession remains human-approval gated.

## Fail-closed release policy

For the Batch 8 release-readiness checkpoint, every required family must be present with at least one recorded sample, `success_rate == 1.0`, and `mean_quality_score == 1.0`. The policy is intentionally stricter than the general model benchmark defaults because these cases describe memory integrity and isolation properties rather than subjective model quality.

A failed critical case cannot be averaged away by later successes. For example, one pass and one failure in `memory_scope_isolation` produces a 0.5 success rate and blocks readiness. Likewise, a case marked passed with quality below 1.0 blocks readiness so incomplete evidence cannot be represented as fully verified.

## Evidence model

`MemoryBenchmarkObservation` converts bounded evaluator observations into the existing `BenchmarkRun` schema using model identity `dpn-memory-runtime-v10`. Runs can therefore be stored in the normal JSONL `BenchmarkLaboratory`, summarized by the normal laboratory, and evaluated by the normal v10 readiness gate.

The benchmark layer does not fabricate successful observations. CI/unit tests validate the gate mechanics, while release evidence must come from actual executed memory tests or an evaluator that records observed outcomes.

## Current checkpoint

The benchmark gate itself is part of Batch 8. Batch 8 is not considered benchmark-ready merely because the gate exists; the exact branch head must pass CI/security/recovery and the final audit must map executed test evidence to all eight mandatory families before PR #93 can be considered merge-ready.
