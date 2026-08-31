# Cognitive Kernel and Evidence System

The cognitive kernel is deterministic control logic around model reasoning. It does not expose private chain-of-thought and does not assume the model is correct.

## Goal contract

A contract records the objective, task classes, required capabilities, deliverables, success criteria, constraints, risks, unknowns, confidence, and side-effect requirements. It narrows phrases such as “do everything” into a checkable operation.

## Plan controls

Plans are limited, acyclic, dependency-aware, and normalized to supported specialists. Every step includes evidence requirements, maximum attempts, and rollback guidance.

## Evidence

Evidence may include tool traces, command results, test output, file paths, hashes, screenshots, media probes, document inspection, or attributable web sources. A model-written statement is not accepted by itself as proof.

## Verification and repair

The deterministic verifier checks reported artifacts within the workspace, including existence and nonzero size. Failed verification can trigger a bounded repair pass. Independent reviewers then evaluate requirements, security, operations, and adversarial failure modes. A weighted quorum produces the final verdict.