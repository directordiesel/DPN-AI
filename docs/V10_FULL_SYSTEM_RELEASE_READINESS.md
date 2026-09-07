# DPN AI v10.0.0 — Batch 15 Full-System Release Readiness

Batch 15 converts full-system integration from descriptive evidence into an executable, fail-closed release checkpoint.

## Scope

The integration gate requires evidence for all approved v10 subsystem families: model intelligence, benchmark laboratory, autonomous coding, computer/browser control, multimodal runtime, long-horizon missions, connector protocol, deep research, layered memory, artifact generation, voice, proactive intelligence, specialist agents, capability marketplace, and governed self-improvement.

The gate is evidence-only. It does not invoke providers, tools, connectors, plugins, repository writes, deployments, or approval decisions.

## Mandatory release families

`app/full_system_release_v10.py` defines ten immutable Batch 15 release families mapped to exact pytest node IDs:

1. subsystem completeness;
2. integrated ready path;
3. blocked subsystem fail-closed behavior;
4. approval-boundary preservation;
5. evidence identity integrity;
6. non-executing readiness evidence;
7. verified early-batch attestations for Batches 1–7;
8. concrete cross-batch release binding for the late release-gated subsystems;
9. fail-closed handling when a late subsystem release payload is not ready;
10. rejection of any release payload that attempts to turn readiness evidence into execution authorization.

The last four families bind the abstract integration authority to concrete historical merge attestations and the live release-output contracts. Missing, failed, or unexpected families block readiness. Arbitrary caller-supplied test IDs cannot substitute for the manifest.

## CI execution

`app/full_system_release_ci_v10.py` executes only the exact mandatory manifest. `.github/scripts/full_system_release_readiness_v10.py` provides the repository-root-safe CI entrypoint. GitHub Actions runs the dedicated Batch 15 gate on Ubuntu/Python 3.11 after the Batch 8–14 gates.

The full repository test suite still runs across Ubuntu and Windows on Python 3.11 and 3.12. Batch 15 is additional release evidence, not a replacement for regression coverage.

## Security boundary

Full-system readiness is not execution authorization. Integration evidence cannot claim external side effects, and any subsystem whose approval boundary is not preserved blocks readiness. Destructive or high-risk operations continue to rely on the existing ToolRegistry/ApprovalSecurity and subsystem-specific controls.

## Completion rule

Batch 15 can be marked complete only when the exact branch head passes the normal CI/security/repository-health/runtime checks and the dedicated Batch 15 gate returns `ready=true` with all ten mandatory families passing.
