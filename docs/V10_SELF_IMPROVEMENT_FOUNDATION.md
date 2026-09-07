# DPN AI v10.0.0 — Benchmark-Gated Self-Improvement Foundation

## Scope

Batch 14 begins the approval-controlled self-improvement loop inside the existing v10.0.0 program. It extends the existing autonomous coding runtime and benchmark laboratory instead of creating a second code-execution or benchmark authority.

## Existing authorities reused

The foundation reuses:

- `CodingMission.require_ready()` from the autonomous coding runtime for validation, review, security-review, CI, and repair evidence;
- `BenchmarkLaboratory.summarize()` and recorded `BenchmarkRun` evidence for deterministic baseline/candidate comparison;
- the existing repository/ToolRegistry/ApprovalSecurity architecture for any future application step.

The self-improvement controller itself performs no repository writes, tool execution, merge, plugin activation, approval mutation, or external action.

## Candidate gate

A candidate can be evaluated only when:

1. the coding mission is already fully `READY`;
2. the benchmark model identity is explicit;
3. every required benchmark family has both baseline and candidate evidence;
4. minimum sample requirements are satisfied;
5. candidate success and quality meet policy thresholds;
6. success and quality do not regress beyond policy;
7. latency does not regress beyond the bounded policy ratio.

The default foundation policy is intentionally strict: success and quality must be 1.0, no success/quality regression is permitted, and latency regression is limited to 25 percent.

## Durable evidence

Each evaluation receives a SHA-256 digest bound to:

- candidate ID;
- coding mission ID/repository/objective;
- affected files and tests;
- benchmark model identity;
- required benchmark families;
- normalized per-family baseline/candidate evidence.

`SelfImprovementEvidenceStore` persists evaluation receipts atomically. Corrupt state fails closed. A repeated identical receipt is idempotent; a conflicting receipt under the same digest is rejected.

JSON persistence rejects non-finite values.

## Promotion boundary

Passing the benchmark gate is not authorization.

`request_promotion()` returns only a non-executable `ImprovementPromotionRequest` with:

- `approval_required=true`;
- `execution_authorized=false`;
- `required_authority="explicit_human_approval"`.

The request can be produced only when exact durable evaluation evidence still exists. Failed, missing, or tampered evidence cannot request promotion.

No model-visible self-improvement execution tool is introduced in this checkpoint.

## Security properties

This foundation deliberately prevents:

- self-approval;
- benchmark-family substitution;
- promotion without a READY coding mission;
- silent benchmark regression;
- promotion from missing or tampered durable evidence;
- direct repository edits or merges;
- direct ToolRegistry `_invoke()` use;
- direct marketplace activation;
- autonomous execution after benchmark success.

## Next checkpoint

The next Batch 14 work should bind evaluations to trusted executed benchmark manifests and exact code/commit identity, then route approved application through an existing governed repository-change path while preserving ToolRegistry/ApprovalSecurity and human approval as the final authority.
