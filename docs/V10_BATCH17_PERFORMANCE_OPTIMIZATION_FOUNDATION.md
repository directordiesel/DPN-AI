# DPN AI v10.0.0 — Batch 17 Performance + Benchmark Optimization

Batch 17 optimizes the integrated v10 platform without weakening correctness, security, benchmark coverage, or approval boundaries.

## Foundation

`app/performance_optimization_v10.py` evaluates explicit baseline and candidate `BenchmarkRun` evidence from the existing Benchmark Laboratory. It does not execute benchmarks, modify routing, apply code, merge changes, deploy software, or authorize tools.

A candidate must use the exact same task IDs for every required benchmark family. Missing, duplicate, substituted, or omitted tasks fail closed. Default policy preserves 100% success and quality, allows no latency/retry/token regression, and requires at least one measurable resource improvement.

## Durable evidence

`app/performance_evidence_v10.py` records append-only optimization receipts bound to the full normalized evaluation with SHA-256. Identical replay is idempotent. Corrupt state, conflicting evidence under the same candidate digest, or any receipt claiming `execution_authorized=true` fails closed.

## Governed performance profiles

`app/performance_profiles_v10.py` defines immutable host-owned optimization profiles:

- `balanced_platform` — broad cross-capability optimization over model intelligence, autonomous coding, multimodal, memory, artifacts, voice, proactive intelligence, specialists, marketplace, and self-improvement.
- `interactive_latency` — latency-sensitive model/multimodal/voice/proactive workloads.
- `agent_efficiency` — autonomous coding, memory, specialist, and self-improvement efficiency with strict token controls.

Unknown or malformed profile identities fail closed. Profiles do not grant execution authority and cannot waive correctness or quality requirements.

## Security and anti-gaming boundary

- exact baseline/candidate task-set parity is mandatory;
- duplicate task IDs are rejected;
- success and quality regression are independently gated;
- token evidence must be complete for every task or absent for every task;
- baseline/candidate token availability must match;
- zero-resource baselines are handled with finite ratios;
- candidate/model/family/profile identities are strict strings;
- non-finite evidence is prohibited from durable JSON;
- optimization evidence always carries `execution_authorized=false`;
- no ToolRegistry `_invoke()` bypass, model-controlled benchmark pass flag, deployment, connector mutation, capability activation, self-merge, or routing mutation is introduced.

## Verification

Regression coverage includes genuine improvements, omitted-task gaming, duplicate evidence, correctness/quality tradeoffs, retry/token regressions, no-op candidates, incomplete token evidence, zero-resource baselines, malformed policies/identities, durable receipt replay, corrupt receipt handling, authorization-claim rejection, and profile validation.

Batch 17 remains incomplete until cross-capability acceptance evidence, an immutable release manifest, executable release harness, dedicated CI gate, and exact-head completion evidence are green.
